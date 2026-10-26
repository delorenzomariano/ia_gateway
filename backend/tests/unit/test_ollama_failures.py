"""Fallas del adaptador de Ollama: caída, timeouts por fase y respuestas inválidas (US3)."""

import asyncio
import json

import httpx
import pytest
import respx

from ia_gateway.config import Settings
from ia_gateway.llm.base import (
    ChatMessage,
    LLMInvalidResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from ia_gateway.llm.ollama import OllamaClient

BASE = "http://ollama.test:11434"
MESSAGES = [ChatMessage(role="user", content="hola")]


def line(content: str, done: bool = False) -> bytes:
    return json.dumps({"message": {"content": content}, "done": done}).encode() + b"\n"


class SlowStream(httpx.AsyncByteStream):
    """Emite (espera, bytes) en orden: permite simular demoras entre fragmentos."""

    def __init__(self, steps):
        self.steps = steps

    async def __aiter__(self):
        for delay, data in self.steps:
            await asyncio.sleep(delay)
            yield data

    async def aclose(self):
        pass


def make_client(**overrides) -> OllamaClient:
    settings = Settings(
        _env_file=None,
        ollama_base_url=BASE,
        timeout_first_chunk_s=overrides.pop("first", 1),
        timeout_idle_s=overrides.pop("idle", 1),
        timeout_total_s=overrides.pop("total", 5),
        **overrides,
    )
    return OllamaClient(settings)


async def collect(client):
    try:
        return [chunk async for chunk in client.chat_stream(MESSAGES)]
    finally:
        await client.aclose()


@respx.mock
async def test_connection_refused_retries_once_then_unavailable(monkeypatch):
    sleeps = []
    real_sleep = asyncio.sleep

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr("ia_gateway.llm.ollama.asyncio.sleep", fake_sleep)
    route = respx.post(f"{BASE}/api/chat").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(LLMUnavailableError):
        await collect(make_client())
    assert route.call_count == 2
    assert sleeps == [0.5]


@respx.mock
async def test_retry_succeeds_on_second_attempt():
    route = respx.post(f"{BASE}/api/chat").mock(
        side_effect=[httpx.ConnectError("refused"), httpx.Response(200, content=line("ok", True))]
    )
    chunks = await collect(make_client())
    assert "".join(c.text for c in chunks) == "ok"
    assert route.call_count == 2


@respx.mock
async def test_no_retry_after_receiving_chunks():
    class Broken(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield line("parcial")
            raise httpx.ReadError("conexión perdida")

    route = respx.post(f"{BASE}/api/chat").mock(return_value=httpx.Response(200, stream=Broken()))
    with pytest.raises(LLMUnavailableError):
        await collect(make_client())
    assert route.call_count == 1


@respx.mock
async def test_first_chunk_timeout():
    respx.post(f"{BASE}/api/chat").mock(
        return_value=httpx.Response(200, stream=SlowStream([(0.5, line("tarde", True))]))
    )
    with pytest.raises(LLMTimeoutError):
        await collect(make_client(first=0.1))


@respx.mock
async def test_idle_timeout_between_chunks():
    respx.post(f"{BASE}/api/chat").mock(
        return_value=httpx.Response(
            200, stream=SlowStream([(0, line("uno")), (0.5, line("dos", True))])
        )
    )
    with pytest.raises(LLMTimeoutError):
        await collect(make_client(idle=0.1))


@respx.mock
async def test_total_timeout():
    steps = [(0.06, line(str(i))) for i in range(10)] + [(0, line("", True))]
    respx.post(f"{BASE}/api/chat").mock(return_value=httpx.Response(200, stream=SlowStream(steps)))
    with pytest.raises(LLMTimeoutError):
        await collect(make_client(idle=0.5, total=0.2))


@respx.mock
async def test_malformed_line_is_invalid_response():
    respx.post(f"{BASE}/api/chat").mock(
        return_value=httpx.Response(200, content=line("hola") + b"{no es json\n")
    )
    with pytest.raises(LLMInvalidResponseError):
        await collect(make_client())


@respx.mock
async def test_http_error_from_ollama_is_invalid_response():
    respx.post(f"{BASE}/api/chat").mock(
        return_value=httpx.Response(404, json={"error": "model 'x' not found"})
    )
    with pytest.raises(LLMInvalidResponseError):
        await collect(make_client())


@respx.mock
async def test_error_object_in_stream_is_invalid_response():
    respx.post(f"{BASE}/api/chat").mock(
        return_value=httpx.Response(200, content=b'{"error": "out of memory"}\n')
    )
    with pytest.raises(LLMInvalidResponseError):
        await collect(make_client())
