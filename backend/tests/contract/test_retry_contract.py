"""Contrato de POST /conversations/{id}/messages/retry."""

import uuid

from ia_gateway.llm.base import LLMTimeoutError

from ..fakes import text_reply
from ..sse_utils import parse_sse
from .schema_utils import assert_matches_schema

JSON = {"Accept": "application/json"}
SSE = {"Accept": "text/event-stream"}


async def _failed_conversation(client, fake_llm) -> str:
    fake_llm.queue([LLMTimeoutError("lento")])
    conv_id = (await client.post("/api/v1/conversations")).json()["id"]
    await client.post(
        f"/api/v1/conversations/{conv_id}/messages", json={"content": "pregunta"}, headers=JSON
    )
    return conv_id


async def test_retry_json_regenerates_without_duplicating_user_message(client, fake_llm):
    conv_id = await _failed_conversation(client, fake_llm)
    fake_llm.queue(text_reply("Respuesta nueva."))
    response = await client.post(f"/api/v1/conversations/{conv_id}/messages/retry", headers=JSON)
    assert response.status_code == 200
    body = response.json()
    assert_matches_schema(body, "SendMessageResponse")
    assert body["user_message"]["content"] == "pregunta"
    assert body["assistant_message"]["content"] == "Respuesta nueva."

    history = (await client.get(f"/api/v1/conversations/{conv_id}")).json()["messages"]
    assert [m["role"] for m in history] == ["user", "assistant"]
    # el contexto enviado al modelo tiene la pregunta una sola vez
    assert [m.content for m in fake_llm.calls[-1].messages[1:]] == ["pregunta"]


async def test_retry_stream(client, fake_llm):
    conv_id = await _failed_conversation(client, fake_llm)
    fake_llm.queue(text_reply("De nuevo."))
    response = await client.post(f"/api/v1/conversations/{conv_id}/messages/retry", headers=SSE)
    events = parse_sse(response.text)
    assert [name for name, _ in events][0] == "message.start"
    assert events[0][1]["user_message"]["content"] == "pregunta"
    assert events[-1][0] == "message.end"
    assert events[-1][1]["assistant_message"]["content"] == "De nuevo."


async def test_nothing_to_retry_after_complete_answer(client):
    conv_id = (await client.post("/api/v1/conversations")).json()["id"]
    await client.post(
        f"/api/v1/conversations/{conv_id}/messages", json={"content": "hola"}, headers=JSON
    )
    response = await client.post(f"/api/v1/conversations/{conv_id}/messages/retry", headers=JSON)
    assert response.status_code == 422
    body = response.json()
    assert_matches_schema(body, "ErrorResponse")
    assert body["error"]["code"] == "NOTHING_TO_RETRY"


async def test_nothing_to_retry_in_empty_conversation(client):
    conv_id = (await client.post("/api/v1/conversations")).json()["id"]
    response = await client.post(f"/api/v1/conversations/{conv_id}/messages/retry", headers=JSON)
    assert response.json()["error"]["code"] == "NOTHING_TO_RETRY"


async def test_retry_unknown_conversation(client):
    response = await client.post(
        f"/api/v1/conversations/{uuid.uuid4()}/messages/retry", headers=JSON
    )
    assert response.status_code == 404
