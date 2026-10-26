import json

import httpx
import pytest
import respx

from ia_gateway.config import Settings
from ia_gateway.llm.base import ChatMessage
from ia_gateway.llm.ollama import OllamaClient
from ia_gateway.observability.correlation import correlation_id

BASE = "http://ollama.test:11434"


def ndjson(*objs) -> bytes:
    return b"".join(json.dumps(o).encode() + b"\n" for o in objs)


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, ollama_base_url=BASE, ollama_model="qwen3:4b")


@pytest.fixture
async def client(settings):
    c = OllamaClient(settings)
    yield c
    await c.aclose()


async def collect(client, messages, tools=None):
    return [chunk async for chunk in client.chat_stream(messages, tools)]


@respx.mock
async def test_chat_stream_request_and_parsing(client):
    route = respx.post(f"{BASE}/api/chat").mock(
        return_value=httpx.Response(
            200,
            content=ndjson(
                {"message": {"role": "assistant", "content": "", "thinking": "pienso…"}},
                {"message": {"role": "assistant", "content": "Hola"}, "done": False},
                {"message": {"role": "assistant", "content": " mundo"}, "done": False},
                {
                    "message": {"role": "assistant", "content": ""},
                    "done": True,
                    "prompt_eval_count": 12,
                    "eval_count": 3,
                },
            ),
        )
    )
    token = correlation_id.set("corr-1")
    try:
        messages = [ChatMessage(role="system", content="S"), ChatMessage(role="user", content="Hi")]
        chunks = await collect(client, messages)
    finally:
        correlation_id.reset(token)

    request = route.calls.last.request
    body = json.loads(request.content)
    assert body["model"] == "qwen3:4b"
    assert body["stream"] is True
    assert "think" not in body  # por defecto no se envía (ver config.ollama_think)
    assert body["options"]["num_ctx"] == 8192
    assert body["messages"] == [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "Hi"},
    ]
    assert "tools" not in body
    assert request.headers["X-Correlation-ID"] == "corr-1"

    assert "".join(c.text for c in chunks) == "Hola mundo"
    assert all("pienso" not in c.text for c in chunks)
    last = chunks[-1]
    assert last.done and last.prompt_tokens == 12 and last.completion_tokens == 3


@respx.mock
async def test_think_is_sent_when_configured():
    settings = Settings(_env_file=None, ollama_base_url=BASE, ollama_think=True)
    reply = ndjson({"message": {"content": "ok"}, "done": True})
    route = respx.post(f"{BASE}/api/chat").mock(return_value=httpx.Response(200, content=reply))
    client = OllamaClient(settings)
    try:
        await collect(client, [ChatMessage(role="user", content="Hi")])
    finally:
        await client.aclose()
    assert json.loads(route.calls.last.request.content)["think"] is True


@respx.mock
async def test_leading_think_block_in_content_is_removed(client):
    respx.post(f"{BASE}/api/chat").mock(
        return_value=httpx.Response(
            200,
            content=ndjson(
                {"message": {"content": "<thi"}},
                {"message": {"content": "nk>razono en inglés"}},
                {"message": {"content": " un rato</think>\n\nLa capital"}},
                {"message": {"content": " es París."}, "done": True},
            ),
        )
    )
    chunks = await collect(client, [ChatMessage(role="user", content="?")])
    assert "".join(c.text for c in chunks) == "La capital es París."


@respx.mock
async def test_text_that_only_looks_like_a_tag_is_kept(client):
    respx.post(f"{BASE}/api/chat").mock(
        return_value=httpx.Response(
            200,
            content=ndjson(
                {"message": {"content": "<"}},
                {"message": {"content": "b> no es un bloque"}, "done": True},
            ),
        )
    )
    chunks = await collect(client, [ChatMessage(role="user", content="?")])
    assert "".join(c.text for c in chunks) == "<b> no es un bloque"


@respx.mock
async def test_tools_and_tool_messages_are_sent_in_ollama_format(client):
    from ia_gateway.llm.base import ToolCall, ToolSpec

    route = respx.post(f"{BASE}/api/chat").mock(
        return_value=httpx.Response(
            200,
            content=ndjson(
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {"function": {"name": "current_time", "arguments": {"tz": "UTC"}}}
                        ],
                    },
                    "done": True,
                }
            ),
        )
    )
    tools = [ToolSpec(name="current_time", description="Hora", parameters={"type": "object"})]
    messages = [
        ChatMessage(role="user", content="hora"),
        ChatMessage(
            role="assistant", content="", tool_calls=[ToolCall(name="current_time", arguments={})]
        ),
        ChatMessage(role="tool", content='{"iso": "x"}', tool_name="current_time"),
    ]
    chunks = await collect(client, messages, tools)

    body = json.loads(route.calls.last.request.content)
    assert body["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "current_time",
                "description": "Hora",
                "parameters": {"type": "object"},
            },
        }
    ]
    assert body["messages"][1]["tool_calls"] == [
        {"function": {"name": "current_time", "arguments": {}}}
    ]
    assert body["messages"][2] == {
        "role": "tool",
        "content": '{"iso": "x"}',
        "tool_name": "current_time",
    }
    assert chunks[-1].tool_calls[0].name == "current_time"
    assert chunks[-1].tool_calls[0].arguments == {"tz": "UTC"}


@respx.mock
async def test_health_reports_model_availability(client):
    respx.get(f"{BASE}/api/tags").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "qwen3:4b"}]})
    )
    health = await client.health()
    assert health.ok and health.model_available and health.model == "qwen3:4b"


@respx.mock
async def test_health_model_missing(client):
    respx.get(f"{BASE}/api/tags").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "otro:1b"}]})
    )
    health = await client.health()
    assert health.ok and not health.model_available


@respx.mock
async def test_health_unreachable(client):
    respx.get(f"{BASE}/api/tags").mock(side_effect=httpx.ConnectError("down"))
    health = await client.health()
    assert not health.ok and not health.model_available and health.detail
