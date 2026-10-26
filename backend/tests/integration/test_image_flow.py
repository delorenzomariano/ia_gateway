"""US1/US2 (feature 002): enviar una imagen, reconocer su texto y responder con él."""

import json
import logging
import uuid

import httpx
import pytest

from ia_gateway.chat.context import IMAGE_TEXT_INSTRUCTION
from ia_gateway.main import create_app
from ia_gateway.observability.logging import JsonFormatter

from ..contract.schema_utils import assert_matches_schema
from ..fakes import FakeLLMClient, FakeOcrEngine
from ..images import image_payload, png_with_text
from ..sse_utils import parse_sse

JSON = {"Accept": "application/json"}
SSE = {"Accept": "text/event-stream"}
OCR_TEXT = "Error 404: página no encontrada"


class Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(JsonFormatter())
        self.records: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(json.loads(self.format(record)))


@pytest.fixture
def ocr_logs():
    collector = Collector()
    logger = logging.getLogger("ia_gateway.ocr")
    logger.addHandler(collector)
    yield collector
    logger.removeHandler(collector)


async def _conversation(client) -> str:
    return (await client.post("/api/v1/conversations")).json()["id"]


async def _send(client, conv_id, body, headers=JSON):
    return await client.post(
        f"/api/v1/conversations/{conv_id}/messages", json=body, headers=headers
    )


async def test_image_and_question_reach_the_model(client, fake_llm, fake_ocr):
    fake_ocr.queue_text(OCR_TEXT)
    conv_id = await _conversation(client)
    response = await _send(client, conv_id, {"content": "¿Qué dice?", "image": image_payload()})
    assert response.status_code == 200

    context = fake_llm.calls[-1].messages
    assert context[0].role == "system"
    assert context[0].content.endswith(IMAGE_TEXT_INSTRUCTION)
    assert context[-1].role == "user"
    assert context[-1].content.startswith("¿Qué dice?\n\n")
    assert f"<<<\n{OCR_TEXT}\n>>>" in context[-1].content


async def test_image_without_question_uses_default_prompt(client, fake_llm, fake_ocr):
    fake_ocr.queue_text(OCR_TEXT)
    conv_id = await _conversation(client)
    response = await _send(client, conv_id, {"image": image_payload()})
    assert response.status_code == 200
    assert (
        fake_llm.calls[-1].messages[-1].content.startswith("Analizá el texto de la imagen adjunta.")
    )


async def test_follow_up_keeps_the_image_text(client, fake_llm, fake_ocr):
    fake_ocr.queue_text(OCR_TEXT)
    conv_id = await _conversation(client)
    await _send(client, conv_id, {"content": "¿Qué dice?", "image": image_payload()})
    await _send(client, conv_id, {"content": "¿Qué número aparece?"})

    context = fake_llm.calls[-1].messages
    assert any(OCR_TEXT in m.content for m in context if m.role == "user")
    assert context[-1].content == "¿Qué número aparece?"
    assert fake_ocr.calls == 1


async def test_stream_start_includes_attachment(client, fake_ocr):
    fake_ocr.queue_text(OCR_TEXT)
    conv_id = await _conversation(client)
    response = await _send(client, conv_id, {"content": "hola", "image": image_payload()}, SSE)
    events = parse_sse(response.text)
    assert events[0][0] == "message.start"
    assert events[0][1]["user_message"]["attachment"]["text"] == OCR_TEXT
    assert events[-1][0] == "message.end"


async def test_unknown_conversation_does_not_run_ocr(client, fake_ocr):
    response = await _send(client, str(uuid.uuid4()), {"image": image_payload()})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"
    assert fake_ocr.calls == 0


async def test_busy_conversation_does_not_run_ocr(client, fake_ocr, services_of):
    conv_id = await _conversation(client)
    release = services_of(client).locks.acquire(conv_id)
    try:
        response = await _send(client, conv_id, {"image": image_payload()})
    finally:
        release()
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "GENERATION_IN_PROGRESS"
    assert fake_ocr.calls == 0


async def test_image_bytes_are_not_stored(client, settings, tmp_path, fake_ocr):
    data = png_with_text("Guardame solo el texto")
    payload = image_payload(data)
    conv_id = await _conversation(client)
    assert (await _send(client, conv_id, {"image": payload})).status_code == 200

    db_files = {p.name for p in tmp_path.iterdir()}
    assert db_files <= {"test.db", "test.db-wal", "test.db-shm"}
    for name in db_files:
        raw = (tmp_path / name).read_bytes()
        assert b"\x89PNG" not in raw
        assert payload["data"][:64].encode() not in raw


async def test_ocr_log_has_metadata_but_no_text(client, fake_ocr, ocr_logs):
    fake_ocr.queue_text(OCR_TEXT)
    conv_id = await _conversation(client)
    await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"image": image_payload()},
        headers={**JSON, "X-Correlation-ID": "corr-ocr-1"},
    )
    [record] = [r for r in ocr_logs.records if r["message"] == "ocr_completed"]
    assert record["correlation_id"] == "corr-ocr-1"
    assert record["media_type"] == "image/png"
    for key in ("size_bytes", "width", "height", "duration_ms", "chars", "dropped_words"):
        assert isinstance(record[key], int), key
    assert record["truncated"] is False
    assert OCR_TEXT not in json.dumps(record, ensure_ascii=False)


# --- US2: el texto reconocido queda disponible en el historial ---------------------------


async def test_get_conversation_returns_attachment(client, fake_ocr):
    fake_ocr.queue_text(OCR_TEXT)
    conv_id = await _conversation(client)
    await _send(client, conv_id, {"content": "¿Qué dice?", "image": image_payload()})
    await _send(client, conv_id, {"content": "gracias"})

    body = (await client.get(f"/api/v1/conversations/{conv_id}")).json()
    assert_matches_schema(body, "ConversationWithMessages")
    user_with_image, _, user_plain, _ = body["messages"]
    assert user_with_image["attachment"] == {
        "filename": "captura.png",
        "media_type": "image/png",
        "size_bytes": len(png_with_text()),
        "text": OCR_TEXT,
        "truncated": False,
    }
    assert user_plain.get("attachment") is None


async def test_attachment_survives_restart(settings):
    ocr = FakeOcrEngine(default=OCR_TEXT)

    async def run(app, fn):
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
                return await fn(c)

    async def send(c):
        conv_id = await _conversation(c)
        await _send(c, conv_id, {"image": image_payload()})
        return conv_id

    conv_id = await run(create_app(settings, llm_client=FakeLLMClient(), ocr_engine=ocr), send)

    async def read(c):
        return (await c.get(f"/api/v1/conversations/{conv_id}")).json()

    body = await run(create_app(settings, llm_client=FakeLLMClient(), ocr_engine=ocr), read)
    assert body["messages"][0]["attachment"]["text"] == OCR_TEXT
