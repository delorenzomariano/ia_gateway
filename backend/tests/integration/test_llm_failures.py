"""Fallas del modelo vistas desde la API (US3, SC-003)."""

import pytest

from ia_gateway.llm.base import (
    LLMChunk,
    LLMHealth,
    LLMInvalidResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
)

from ..contract.schema_utils import assert_matches_schema
from ..fakes import text_reply
from ..sse_utils import parse_sse

JSON = {"Accept": "application/json"}
SSE = {"Accept": "text/event-stream"}

CASES = [
    (LLMUnavailableError("caído"), 503, "LLM_UNAVAILABLE"),
    (LLMTimeoutError("lento"), 504, "LLM_TIMEOUT"),
    (LLMInvalidResponseError("basura"), 502, "LLM_INVALID_RESPONSE"),
]


async def _conversation(client) -> str:
    return (await client.post("/api/v1/conversations")).json()["id"]


@pytest.mark.parametrize(("exc", "status", "code"), CASES)
async def test_json_mode_maps_llm_errors(client, fake_llm, services_of, exc, status, code):
    fake_llm.queue([exc])
    conv_id = await _conversation(client)
    response = await client.post(
        f"/api/v1/conversations/{conv_id}/messages", json={"content": "hola"}, headers=JSON
    )
    assert response.status_code == status
    body = response.json()
    assert_matches_schema(body, "ErrorResponse")
    assert body["error"]["code"] == code
    assert body["error"]["correlation_id"] == response.headers["X-Correlation-ID"]
    assert body["error"]["message"]  # texto en español para el usuario

    services = services_of(client)
    messages = await services.repository.list_messages(conv_id)
    assert [(m.role, m.status, m.error_code) for m in messages] == [
        ("user", "complete", None),
        ("assistant", "error", code),
    ]
    assert not services.locks.is_busy(conv_id)


async def test_empty_model_response_is_invalid(client, fake_llm):
    fake_llm.queue([LLMChunk(text="  \n"), LLMChunk(done=True)])
    conv_id = await _conversation(client)
    response = await client.post(
        f"/api/v1/conversations/{conv_id}/messages", json={"content": "hola"}, headers=JSON
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "LLM_INVALID_RESPONSE"


@pytest.mark.parametrize(("exc", "status", "code"), CASES)
async def test_stream_mode_emits_error_event(client, fake_llm, services_of, exc, status, code):
    fake_llm.queue([*text_reply("Hola")[:-1], exc])
    conv_id = await _conversation(client)
    response = await client.post(
        f"/api/v1/conversations/{conv_id}/messages", json={"content": "hola"}, headers=SSE
    )
    assert response.status_code == 200
    events = parse_sse(response.text)
    assert [name for name, _ in events] == ["message.start", "delta", "error"]
    error = events[-1][1]
    assert error["error"]["code"] == code
    assert error["error"]["correlation_id"] == response.headers["X-Correlation-ID"]
    assert_matches_schema(error["assistant_message"], "Message")
    assert error["assistant_message"]["status"] == "error"
    assert not services_of(client).locks.is_busy(conv_id)


async def test_health_is_degraded_when_llm_is_down(client, fake_llm):
    fake_llm.health_result = LLMHealth(ok=False, model="x", model_available=False, detail="down")
    response = await client.get("/api/v1/health")
    assert response.status_code == 503
    body = response.json()
    assert_matches_schema(body, "Health")
    assert body["status"] == "degraded"
    assert body["checks"]["llm"]["status"] == "error"


async def test_recovers_after_failure(client, fake_llm):
    fake_llm.queue([LLMUnavailableError("caído")], text_reply("Ya estoy."))
    conv_id = await _conversation(client)
    url = f"/api/v1/conversations/{conv_id}/messages"
    assert (await client.post(url, json={"content": "hola"}, headers=JSON)).status_code == 503
    retry = await client.post(f"{url}/retry", headers=JSON)
    assert retry.status_code == 200
    assert retry.json()["assistant_message"]["content"] == "Ya estoy."

    history = (await client.get(f"/api/v1/conversations/{conv_id}")).json()["messages"]
    assert [(m["role"], m["content"]) for m in history] == [
        ("user", "hola"),
        ("assistant", "Ya estoy."),
    ]
