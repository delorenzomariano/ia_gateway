"""Límite del tamaño del cuerpo: 413 antes de leer y decodificar el JSON (research.md R3)."""

import json

import pytest

from ..contract.schema_utils import assert_matches_schema

JSON = {"Accept": "application/json"}


@pytest.fixture
def settings(settings):
    # Imagen máxima de 3000 bytes → cuerpo máximo = 4000 + 65536 bytes.
    return settings.model_copy(update={"ocr_max_image_bytes": 3000})


async def _conversation(client) -> str:
    return (await client.post("/api/v1/conversations")).json()["id"]


async def test_content_length_over_limit_is_rejected(client, settings, fake_llm):
    conv_id = await _conversation(client)
    body = json.dumps({"content": "x" * (settings.max_request_body_bytes + 10)})
    response = await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        content=body,
        headers={**JSON, "Content-Type": "application/json", "X-Correlation-ID": "corr-413"},
    )
    assert response.status_code == 413
    payload = response.json()
    assert_matches_schema(payload, "ErrorResponse")
    assert payload["error"]["code"] == "IMAGE_TOO_LARGE"
    assert payload["error"]["correlation_id"] == "corr-413"
    assert fake_llm.calls == []


async def test_body_within_limit_passes(client):
    conv_id = await _conversation(client)
    response = await client.post(
        f"/api/v1/conversations/{conv_id}/messages", json={"content": "hola"}, headers=JSON
    )
    assert response.status_code == 200


async def _chunked_post(app, path: str, chunks: list[bytes]) -> tuple[int, dict]:
    """POST sin Content-Length, enviando el cuerpo en partes (como Transfer-Encoding chunked)."""
    pending = list(chunks)
    status = None
    body = b""

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"127.0.0.1"),
            (b"accept", b"application/json"),
            (b"content-type", b"application/json"),
        ],
        "client": ("127.0.0.1", 5000),
        "server": ("127.0.0.1", 80),
    }

    async def receive():
        if pending:
            chunk = pending.pop(0)
            return {"type": "http.request", "body": chunk, "more_body": bool(pending)}
        return {"type": "http.disconnect"}

    async def send(message):
        nonlocal status, body
        if message["type"] == "http.response.start":
            status = message["status"]
        elif message["type"] == "http.response.body":
            body += message.get("body", b"")

    await app(scope, receive, send)
    return status, json.loads(body)


async def test_chunked_body_over_limit_is_rejected(client, settings):
    conv_id = await _conversation(client)
    limit = settings.max_request_body_bytes
    chunks = [b'{"content": "'] + [b"x" * 10_000] * (limit // 10_000 + 2) + [b'"}']
    status, payload = await _chunked_post(
        client.app, f"/api/v1/conversations/{conv_id}/messages", chunks
    )
    assert status == 413
    assert payload["error"]["code"] == "IMAGE_TOO_LARGE"


async def test_chunked_body_within_limit_passes(client):
    conv_id = await _conversation(client)
    status, _ = await _chunked_post(
        client.app,
        f"/api/v1/conversations/{conv_id}/messages",
        [b'{"content": ', b'"hola"}'],
    )
    assert status == 200


async def test_paths_outside_api_are_not_limited(client, settings):
    response = await client.post("/no-api", content=b"x" * (settings.max_request_body_bytes + 10))
    assert response.status_code != 413
