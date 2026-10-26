"""Contrato de streaming (contracts/sse-events.md)."""

from ..fakes import text_reply
from ..sse_utils import parse_sse
from .schema_utils import assert_matches_schema

SSE = {"Accept": "text/event-stream"}


async def test_stream_event_sequence(client, fake_llm):
    fake_llm.queue(text_reply("¡Hola! ", "¿En qué ", "puedo ayudarte?"))
    conv = (await client.post("/api/v1/conversations")).json()

    response = await client.post(
        f"/api/v1/conversations/{conv['id']}/messages", json={"content": "Hola"}, headers=SSE
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["X-Correlation-ID"]

    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert names[0] == "message.start"
    assert names[-1] == "message.end"
    assert set(names[1:-1]) == {"delta"}

    start, end = events[0][1], events[-1][1]
    assert_matches_schema(start["user_message"], "Message")
    assert start["user_message"]["content"] == "Hola"
    assert_matches_schema(end["assistant_message"], "Message")
    assert end["assistant_message"]["id"] == start["assistant_message_id"]
    assert end["assistant_message"]["status"] == "complete"

    text = "".join(data["text"] for name, data in events if name == "delta")
    assert text == end["assistant_message"]["content"] == "¡Hola! ¿En qué puedo ayudarte?"


async def test_stream_errors_before_start_are_json(client):
    response = await client.post(
        "/api/v1/conversations/00000000-0000-4000-8000-000000000000/messages",
        json={"content": "Hola"},
        headers=SSE,
    )
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"


async def test_json_is_default_without_accept_header(client):
    conv = (await client.post("/api/v1/conversations")).json()
    response = await client.post(
        f"/api/v1/conversations/{conv['id']}/messages", json={"content": "Hola"}
    )
    assert response.headers["content-type"].startswith("application/json")
    assert_matches_schema(response.json(), "SendMessageResponse")
