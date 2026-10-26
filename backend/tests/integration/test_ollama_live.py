"""Pruebas contra un Ollama real (excluidas por defecto): `uv run pytest -m ollama -s`.

Usan IA_GATEWAY_OLLAMA_BASE_URL / IA_GATEWAY_OLLAMA_MODEL del entorno (o los valores por
defecto) y una base SQLite temporal.
"""

import logging
import statistics

import httpx
import pytest

from ia_gateway.config import Settings
from ia_gateway.main import create_app

from ..sse_utils import parse_sse

pytestmark = pytest.mark.ollama

SSE = {"Accept": "text/event-stream"}


@pytest.fixture
async def live_client(tmp_path):
    settings = Settings(database_path=str(tmp_path / "live.db"), serve_frontend=False)
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport, base_url="http://t", timeout=300
        ) as client:
            yield client


async def _new_conversation(client) -> str:
    return (await client.post("/api/v1/conversations")).json()["id"]


async def test_health_reports_model_available(live_client):
    response = await live_client.get("/api/v1/health")
    body = response.json()
    assert response.status_code == 200, body
    assert body["checks"]["llm"]["model_available"] is True


async def test_json_and_stream_against_real_model(live_client):
    conv_id = await _new_conversation(live_client)
    url = f"/api/v1/conversations/{conv_id}/messages"
    json_reply = await live_client.post(
        url,
        json={"content": "Respondé solo con la palabra: hola"},
        headers={"Accept": "application/json"},
    )
    assert json_reply.status_code == 200, json_reply.text
    assert json_reply.json()["assistant_message"]["content"].strip()
    assert "</think>" not in json_reply.json()["assistant_message"]["content"]

    stream = await live_client.post(url, json={"content": "Ahora decí: chau"}, headers=SSE)
    events = parse_sse(stream.text)
    assert events[0][0] == "message.start"
    assert events[-1][0] == "message.end", events[-1]


async def _ask_streaming(client, conv_id: str, question: str) -> None:
    # httpx.ASGITransport junta toda la respuesta, así que el tiempo hasta el primer fragmento
    # se toma del log `chat_completed` (first_chunk_ms) que emite el backend.
    response = await client.post(
        f"/api/v1/conversations/{conv_id}/messages", json={"content": question}, headers=SSE
    )
    events = parse_sse(response.text)
    assert events[-1][0] == "message.end", events[-1]


async def test_sc002_time_to_first_fragment(live_client, capsys):
    """SC-002: p90 del primer fragmento < 3 s con el modelo cargado (se informa la medición)."""
    conv_id = await _new_conversation(live_client)
    await _ask_streaming(live_client, conv_id, "Hola")  # calentamiento: carga el modelo

    first_chunks: list[float] = []

    class Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if record.getMessage() == "chat_completed" and record.first_chunk_ms is not None:
                first_chunks.append(record.first_chunk_ms / 1000)

    chat_logger = logging.getLogger("ia_gateway.chat")
    collector = Collector()
    chat_logger.addHandler(collector)

    questions = [
        "¿Cuál es la capital de Italia?",
        "Nombrá un color primario.",
        "¿Cuánto es 7 por 8?",
        "Decí un sinónimo de rápido.",
        "¿Qué planeta es el más grande?",
        "Nombrá un instrumento de cuerda.",
        "¿En qué continente está Kenia?",
        "Decí una fruta cítrica.",
        "¿Cuántos días tiene una semana?",
        "Nombrá un océano.",
    ]
    try:
        for question in questions:
            conv = await _new_conversation(live_client)
            await _ask_streaming(live_client, conv, question)
    finally:
        chat_logger.removeHandler(collector)

    first = sorted(first_chunks)
    assert len(first) == len(questions)
    p90 = statistics.quantiles(first, n=10)[-1]
    with capsys.disabled():
        print(f"\nSC-002 primer fragmento (s): {[round(x, 2) for x in first]} | p90={p90:.2f}")
    assert p90 < 3, f"p90 del primer fragmento = {p90:.2f} s (meta < 3 s)"
