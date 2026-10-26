"""FR-021/FR-022: logs JSON con correlation_id; texto de mensajes solo en modo diagnóstico."""

import json

import httpx

from ia_gateway.main import create_app

from ..fakes import FakeLLMClient, FakeOcrEngine, text_reply
from ..images import image_payload

SECRET_QUESTION = "mi pregunta privada 12345"
SECRET_ANSWER = "respuesta privada 67890"


async def _converse(settings) -> None:
    llm = FakeLLMClient()
    llm.queue(text_reply(SECRET_ANSWER, prompt_tokens=11, completion_tokens=4))
    app = create_app(settings, llm_client=llm)
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            conv = (await c.post("/api/v1/conversations")).json()
            response = await c.post(
                f"/api/v1/conversations/{conv['id']}/messages",
                json={"content": SECRET_QUESTION},
                headers={"Accept": "application/json", "X-Correlation-ID": "corr-log-1"},
            )
            assert response.status_code == 200


def _records(output: str) -> list[dict]:
    return [json.loads(line) for line in output.splitlines() if line.startswith("{")]


async def test_logs_are_json_without_message_text(settings, capsys):
    await _converse(settings)
    output = capsys.readouterr().out
    records = _records(output)
    assert records, "no se emitieron logs"

    completed = next(r for r in records if r["message"] == "chat_completed")
    assert completed["correlation_id"] == "corr-log-1"
    assert completed["prompt_tokens"] == 11
    assert completed["completion_tokens"] == 4
    assert completed["total_ms"] is not None
    assert completed["first_chunk_ms"] is not None

    request = next(
        r for r in records if r["message"] == "request" and r["correlation_id"] == "corr-log-1"
    )
    assert request["status"] == 200 and "duration_ms" in request

    assert SECRET_QUESTION not in output
    assert SECRET_ANSWER not in output
    assert not any(r["message"] == "diagnostic_mode_enabled" for r in records)


async def test_diagnostic_mode_logs_text_and_warns(settings, capsys):
    await _converse(settings.model_copy(update={"diagnostic_mode": True}))
    output = capsys.readouterr().out
    records = _records(output)

    warning = next(r for r in records if r.get("event") == "diagnostic_mode_enabled")
    assert warning["level"] == "WARNING"
    completed = next(r for r in records if r["message"] == "chat_completed")
    assert completed["user_text"] == SECRET_QUESTION
    assert completed["assistant_text"] == SECRET_ANSWER


# --- imágenes (feature 002, FR-016) ---------------------------------------------------

SECRET_OCR = "texto secreto de la imagen 4242"


async def _send_image(settings) -> str:
    """Envía una imagen y devuelve su base64."""
    payload = image_payload()
    app = create_app(
        settings, llm_client=FakeLLMClient(), ocr_engine=FakeOcrEngine(default=SECRET_OCR)
    )
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            conv = (await c.post("/api/v1/conversations")).json()
            response = await c.post(
                f"/api/v1/conversations/{conv['id']}/messages",
                json={"content": "¿qué dice?", "image": payload},
                headers={"Accept": "application/json"},
            )
            assert response.status_code == 200
    return payload["data"]


async def test_image_logs_have_no_text_or_image(settings, capsys):
    data = await _send_image(settings)
    output = capsys.readouterr().out
    completed = next(r for r in _records(output) if r["message"] == "ocr_completed")
    assert completed["chars"] == len(SECRET_OCR)
    assert "ocr_text" not in completed
    assert SECRET_OCR not in output
    assert data[:40] not in output


async def test_image_text_is_logged_only_in_diagnostic_mode(settings, capsys):
    await _send_image(settings.model_copy(update={"diagnostic_mode": True}))
    output = capsys.readouterr().out
    completed = next(r for r in _records(output) if r["message"] == "ocr_completed")
    assert completed["ocr_text"] == SECRET_OCR
