"""Adaptador de Ollama (API REST `/api/chat`, `/api/tags`) sobre httpx."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

import httpx

from ia_gateway.config import Settings
from ia_gateway.llm.base import (
    ChatMessage,
    LLMChunk,
    LLMHealth,
    LLMInvalidResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
    ToolCall,
    ToolSpec,
)
from ia_gateway.observability.correlation import HEADER, get_correlation_id


class OllamaClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.model = settings.ollama_model
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.ollama_base_url,
            # La lectura se controla por fase en chat_stream; httpx solo limita la conexión.
            timeout=httpx.Timeout(None, connect=settings.timeout_connect_s),
            transport=transport,
        )

    def _payload(self, messages: list[ChatMessage], tools: list[ToolSpec] | None) -> dict:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [_message_to_ollama(m) for m in messages],
            "stream": True,
            "options": {"num_ctx": self._settings.ollama_num_ctx},
        }
        if self._settings.ollama_think is not None:
            payload["think"] = self._settings.ollama_think
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
        return payload

    async def chat_stream(
        self, messages: list[ChatMessage], tools: list[ToolSpec] | None = None
    ) -> AsyncIterator[LLMChunk]:
        """Timeouts por fase (primer fragmento, inactividad, total) y un único reintento con
        backoff solo si falla la conexión antes de recibir datos (sin efectos todavía)."""
        s = self._settings
        payload = self._payload(messages, tools)
        headers = {HEADER: get_correlation_id()}
        think_filter = ThinkBlockFilter()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + s.timeout_total_s

        def remaining(phase_limit: float) -> float:
            left = deadline - loop.time()
            if left <= 0:
                raise LLMTimeoutError(f"se superó el tiempo total de {s.timeout_total_s} s")
            return min(phase_limit, left)

        for attempt in range(2):
            received_any = False
            try:
                async with self._client.stream(
                    "POST", "/api/chat", json=payload, headers=headers
                ) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", "replace")[:300]
                        raise LLMInvalidResponseError(
                            f"Ollama respondió {response.status_code}: {body}"
                        )
                    lines = aiter(response.aiter_lines())
                    while True:
                        limit = s.timeout_idle_s if received_any else s.timeout_first_chunk_s
                        try:
                            line = await asyncio.wait_for(anext(lines), remaining(limit))
                        except StopAsyncIteration:
                            return
                        except TimeoutError as exc:
                            phase = "inactividad" if received_any else "primer fragmento"
                            raise LLMTimeoutError(f"timeout de {phase}") from exc
                        received_any = True
                        if line.strip():
                            chunk = _parse_line(line)
                            text = think_filter.feed(chunk.text, final=chunk.done)
                            yield replace(chunk, text=text)
                return
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if attempt == 0 and not received_any:
                    await asyncio.sleep(0.5)
                    continue
                raise LLMUnavailableError(f"no se pudo conectar con Ollama: {exc}") from exc
            except (httpx.ReadError, httpx.RemoteProtocolError) as exc:
                raise LLMUnavailableError(f"se perdió la conexión con Ollama: {exc}") from exc
            except httpx.TimeoutException as exc:
                raise LLMTimeoutError(f"timeout de red con Ollama: {exc}") from exc

    async def health(self) -> LLMHealth:
        try:
            response = await self._client.get("/api/tags", timeout=self._settings.timeout_connect_s)
            response.raise_for_status()
            names = {m.get("name") for m in response.json().get("models", [])}
        except (httpx.HTTPError, ValueError) as exc:
            return LLMHealth(ok=False, model=self.model, model_available=False, detail=str(exc))
        available = self.model in names or f"{self.model}:latest" in names
        detail = None if available else f"el modelo {self.model} no está descargado"
        return LLMHealth(ok=True, model=self.model, model_available=available, detail=detail)

    async def aclose(self) -> None:
        await self._client.aclose()


class ThinkBlockFilter:
    """Descarta un bloque `<think>…</think>` al inicio del contenido.

    Algunos modelos lo emiten como texto cuando el servidor no separa el razonamiento en el
    campo `thinking`. Solo se retiene texto mientras puede tratarse del inicio de ese bloque.
    """

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self) -> None:
        self._buffer = ""
        self._state = "start"  # start → (inside →) passthrough

    def feed(self, text: str, final: bool = False) -> str:
        if self._state == "passthrough":
            return text
        self._buffer += text
        if self._state == "start":
            stripped = self._buffer.lstrip()
            if stripped.startswith(self.OPEN):
                self._state = "inside"
            elif self.OPEN.startswith(stripped) and stripped and not final:
                return ""  # podría ser el comienzo de "<think>": esperar más texto
            elif not stripped and not final:
                return ""
            else:
                return self._flush()
        if self._state == "inside":
            end = self._buffer.find(self.CLOSE)
            if end == -1:
                if final:
                    self._buffer = ""
                    self._state = "passthrough"
                return ""
            self._buffer = self._buffer[end + len(self.CLOSE) :].lstrip()
            return self._flush()
        return ""

    def _flush(self) -> str:
        out, self._buffer, self._state = self._buffer, "", "passthrough"
        return out


def _message_to_ollama(message: ChatMessage) -> dict[str, Any]:
    out: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        out["tool_calls"] = [
            {"function": {"name": c.name, "arguments": c.arguments}} for c in message.tool_calls
        ]
    if message.tool_name:
        out["tool_name"] = message.tool_name
    return out


def _parse_line(line: str) -> LLMChunk:
    try:
        data = json.loads(line)
    except json.JSONDecodeError as exc:
        raise LLMInvalidResponseError("Ollama devolvió una línea que no es JSON") from exc
    if not isinstance(data, dict):
        raise LLMInvalidResponseError("Ollama devolvió un objeto inesperado")
    if "error" in data:
        raise LLMInvalidResponseError(f"Ollama informó un error: {data['error']}")

    message = data.get("message") or {}
    content = message.get("content") or ""
    if not isinstance(content, str):
        raise LLMInvalidResponseError("el contenido devuelto por Ollama no es texto")
    # El campo `thinking` (razonamiento interno) se descarta deliberadamente.
    tool_calls = []
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        arguments = function.get("arguments") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {"_raw": arguments}
        tool_calls.append(ToolCall(name=str(function.get("name", "")), arguments=arguments))

    done = bool(data.get("done"))
    return LLMChunk(
        text=content,
        tool_calls=tool_calls,
        done=done,
        prompt_tokens=data.get("prompt_eval_count") if done else None,
        completion_tokens=data.get("eval_count") if done else None,
    )
