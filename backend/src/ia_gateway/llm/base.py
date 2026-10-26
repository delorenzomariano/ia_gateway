"""Interfaz interna del modelo de lenguaje (independiente del proveedor)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

ChatRole = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ChatMessage:
    role: ChatRole
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_name: str | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class LLMChunk:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    done: bool = False
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass(frozen=True)
class LLMHealth:
    ok: bool
    model: str
    model_available: bool
    detail: str | None = None


class LLMError(Exception):
    """Error base de las integraciones con el modelo."""


class LLMUnavailableError(LLMError):
    """No se pudo contactar al servidor del modelo."""


class LLMTimeoutError(LLMError):
    """El modelo excedió alguno de los tiempos máximos."""


class LLMInvalidResponseError(LLMError):
    """El modelo devolvió una respuesta vacía o malformada."""


class LLMClient(Protocol):
    model: str

    def chat_stream(
        self, messages: list[ChatMessage], tools: list[ToolSpec] | None = None
    ) -> AsyncIterator[LLMChunk]: ...

    async def health(self) -> LLMHealth: ...

    async def aclose(self) -> None: ...
