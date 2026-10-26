"""US3 (feature 002): avisos específicos cuando la imagen no sirve o el OCR falla."""

import pytest

from ia_gateway.llm.base import LLMTimeoutError
from ia_gateway.ocr.base import OcrFailedError, OcrUnavailableError

from ..contract.schema_utils import assert_matches_schema
from ..fakes import text_reply
from ..images import fake_png_bytes, image_payload, png_with_text

JSON = {"Accept": "application/json"}
SSE = {"Accept": "text/event-stream"}


async def _conversation(client) -> str:
    return (await client.post("/api/v1/conversations")).json()["id"]


async def _send(client, conv_id, body, headers=JSON):
    return await client.post(
        f"/api/v1/conversations/{conv_id}/messages", json=body, headers=headers
    )


async def _messages(client, conv_id) -> list[dict]:
    return (await client.get(f"/api/v1/conversations/{conv_id}")).json()["messages"]


async def _assert_rejected(client, conv_id, response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert_matches_schema(body, "ErrorResponse")
    assert body["error"]["code"] == code
    # No se guardó nada y el chat de texto sigue funcionando (SC-006).
    assert await _messages(client, conv_id) == []
    ok = await _send(client, conv_id, {"content": "Hola"})
    assert ok.status_code == 200


@pytest.mark.parametrize("headers", [JSON, SSE], ids=["json", "sse"])
async def test_fake_image_is_invalid(client, fake_ocr, headers):
    conv_id = await _conversation(client)
    response = await _send(client, conv_id, {"image": image_payload(fake_png_bytes())}, headers)
    await _assert_rejected(client, conv_id, response, 422, "IMAGE_INVALID")
    assert fake_ocr.calls == 0


async def test_declared_type_must_match(client):
    conv_id = await _conversation(client)
    payload = image_payload(png_with_text(), filename="x.jpg", media_type="image/jpeg")
    response = await _send(client, conv_id, {"image": payload})
    await _assert_rejected(client, conv_id, response, 422, "IMAGE_INVALID")


async def test_invalid_base64(client):
    conv_id = await _conversation(client)
    payload = {**image_payload(), "data": "esto no es base64 ##"}
    response = await _send(client, conv_id, {"image": payload})
    await _assert_rejected(client, conv_id, response, 422, "IMAGE_INVALID")


async def test_image_over_max_bytes(client, settings):
    # La app usa este mismo objeto; el límite del cuerpo ya se fijó al crearla (5 MB).
    settings.ocr_max_image_bytes = 1000
    conv_id = await _conversation(client)
    response = await _send(client, conv_id, {"image": image_payload(b"\x89PNG" + b"0" * 2000)})
    await _assert_rejected(client, conv_id, response, 413, "IMAGE_TOO_LARGE")


@pytest.mark.parametrize("text", ["", "   ", "··", "a -"])
async def test_image_without_text(client, fake_llm, fake_ocr, text):
    fake_ocr.queue_text(text)
    conv_id = await _conversation(client)
    response = await _send(client, conv_id, {"content": "¿qué dice?", "image": image_payload()})
    assert fake_llm.calls == []
    await _assert_rejected(client, conv_id, response, 422, "IMAGE_NO_TEXT")


@pytest.mark.parametrize(
    "error",
    [OcrUnavailableError("sin tesseract"), OcrFailedError("falló")],
    ids=lambda e: type(e).__name__,
)
@pytest.mark.parametrize("headers", [JSON, SSE], ids=["json", "sse"])
async def test_ocr_unavailable(client, fake_ocr, error, headers):
    fake_ocr.queue_error(error)
    conv_id = await _conversation(client)
    response = await _send(client, conv_id, {"image": image_payload()}, headers)
    await _assert_rejected(client, conv_id, response, 503, "OCR_UNAVAILABLE")


async def test_ocr_timeout(client, settings, fake_ocr):
    settings.ocr_timeout_s = 0.05
    fake_ocr.delay_s = 2
    conv_id = await _conversation(client)
    response = await _send(client, conv_id, {"image": image_payload()})
    await _assert_rejected(client, conv_id, response, 504, "OCR_TIMEOUT")


async def test_ocr_disabled(client, settings, fake_ocr):
    settings.ocr_enabled = False
    conv_id = await _conversation(client)
    response = await _send(client, conv_id, {"image": image_payload()})
    await _assert_rejected(client, conv_id, response, 503, "OCR_UNAVAILABLE")
    assert fake_ocr.calls == 0


async def test_retry_after_llm_error_reuses_the_recognized_text(client, fake_llm, fake_ocr):
    fake_ocr.queue_text("Texto de la imagen")
    fake_llm.queue([LLMTimeoutError("lento")], text_reply("Ahora sí"))
    conv_id = await _conversation(client)
    failed = await _send(client, conv_id, {"content": "¿qué dice?", "image": image_payload()})
    assert failed.status_code == 504

    retried = await client.post(f"/api/v1/conversations/{conv_id}/messages/retry", headers=JSON)
    assert retried.status_code == 200
    assert retried.json()["user_message"]["attachment"]["text"] == "Texto de la imagen"
    assert retried.json()["assistant_message"]["content"] == "Ahora sí"
    assert "<<<\nTexto de la imagen\n>>>" in fake_llm.calls[-1].messages[-1].content
    assert fake_ocr.calls == 1
