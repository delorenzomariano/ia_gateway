"""Interfaz de almacenamiento de conversaciones y registros de dominio."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

MessageRole = Literal["user", "assistant", "tool"]
MessageStatus = Literal["complete", "incomplete", "error"]
InvocationStatus = Literal["ok", "error", "rejected"]
ImageMediaType = Literal["image/png", "image/jpeg", "image/webp"]


@dataclass(frozen=True)
class NewAttachment:
    """Metadatos y texto reconocido de una imagen; la imagen en sí no se guarda."""

    filename: str
    media_type: ImageMediaType
    size_bytes: int
    width: int
    height: int
    text: str
    truncated: bool
    ocr_duration_ms: int


@dataclass(frozen=True)
class AttachmentRecord:
    message_id: str
    filename: str
    media_type: ImageMediaType
    size_bytes: int
    width: int
    height: int
    text: str
    truncated: bool
    ocr_duration_ms: int
    created_at: datetime


@dataclass(frozen=True)
class ConversationRecord:
    id: str
    created_at: datetime
    last_activity_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class MessageRecord:
    id: str
    conversation_id: str
    seq: int
    role: MessageRole
    content: str
    status: MessageStatus
    created_at: datetime
    error_code: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_name: str | None = None
    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    attachment: AttachmentRecord | None = None


@dataclass(frozen=True)
class NewMessage:
    """Datos de un mensaje a guardar; el repositorio asigna seq, fecha e id (si no se da)."""

    role: MessageRole
    content: str
    status: MessageStatus = "complete"
    error_code: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_name: str | None = None
    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    id: str | None = None


@dataclass(frozen=True)
class ToolInvocationRecord:
    id: str
    conversation_id: str
    assistant_message_id: str
    tool_name: str
    arguments: Any
    status: InvocationStatus
    duration_ms: int
    created_at: datetime
    result: Any = None
    error: str | None = None


@dataclass(frozen=True)
class NewToolInvocation:
    assistant_message_id: str
    tool_name: str
    arguments: Any
    status: InvocationStatus
    duration_ms: int
    result: Any = None
    error: str | None = None


class ConversationRepository(Protocol):
    async def initialize(self) -> None: ...

    async def ping(self) -> None: ...

    async def create_conversation(self) -> ConversationRecord: ...

    async def get_conversation(self, conversation_id: str) -> ConversationRecord | None:
        """Devuelve None si no existe o si `expires_at <= ahora`."""
        ...

    async def delete_conversation(self, conversation_id: str) -> None: ...

    async def add_message(
        self,
        conversation_id: str,
        message: NewMessage,
        attachment: NewAttachment | None = None,
    ) -> MessageRecord:
        """Asigna `seq` creciente y actualiza `last_activity_at` y `expires_at`.

        `attachment` solo se admite en mensajes `user` y se guarda en la misma transacción.
        """
        ...

    async def list_messages(self, conversation_id: str) -> list[MessageRecord]: ...

    async def delete_message(self, message_id: str) -> None: ...

    async def add_tool_invocation(
        self, conversation_id: str, invocation: NewToolInvocation
    ) -> ToolInvocationRecord: ...

    async def list_tool_invocations(self, conversation_id: str) -> list[ToolInvocationRecord]: ...

    async def delete_expired(self) -> int:
        """Borra conversaciones vencidas (en cascada) y devuelve cuántas borró."""
        ...
