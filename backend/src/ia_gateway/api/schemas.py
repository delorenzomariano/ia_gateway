"""Modelos Pydantic del contrato público (contracts/openapi.yaml)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ia_gateway.storage.repository import (
    AttachmentRecord,
    ConversationRecord,
    ImageMediaType,
    MessageRecord,
)


class Conversation(BaseModel):
    id: str
    created_at: datetime
    last_activity_at: datetime
    expires_at: datetime

    @classmethod
    def from_record(cls, record: ConversationRecord) -> Conversation:
        return cls(
            id=record.id,
            created_at=record.created_at,
            last_activity_at=record.last_activity_at,
            expires_at=record.expires_at,
        )


class Attachment(BaseModel):
    filename: str
    media_type: ImageMediaType
    size_bytes: int
    text: str
    truncated: bool

    @classmethod
    def from_record(cls, record: AttachmentRecord) -> Attachment:
        return cls(
            filename=record.filename,
            media_type=record.media_type,
            size_bytes=record.size_bytes,
            text=record.text,
            truncated=record.truncated,
        )


class Message(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    status: Literal["complete", "incomplete", "error"]
    error_code: str | None = None
    created_at: datetime
    attachment: Attachment | None = None

    @classmethod
    def from_record(cls, record: MessageRecord) -> Message:
        if record.role not in ("user", "assistant"):
            raise ValueError(f"mensaje interno no visible: {record.role}")
        return cls(
            id=record.id,
            role=record.role,
            content=record.content,
            status=record.status,
            error_code=record.error_code,
            created_at=record.created_at,
            attachment=Attachment.from_record(record.attachment) if record.attachment else None,
        )


class ConversationWithMessages(Conversation):
    generation_in_progress: bool
    messages: list[Message]


class ImageInput(BaseModel):
    """Imagen en base64; el contenido real y el tamaño se validan en chat/images.py."""

    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=255)
    media_type: ImageMediaType
    data: str = Field(min_length=4)


class SendMessageRequest(BaseModel):
    """El largo máximo efectivo (MAX_MESSAGE_CHARS) se valida en el endpoint."""

    model_config = ConfigDict(extra="forbid")

    content: str = ""
    image: ImageInput | None = None

    @field_validator("content")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def _content_or_image(self) -> SendMessageRequest:
        if not self.content and self.image is None:
            raise ValueError("el mensaje no puede estar vacío")
        return self


class SendMessageResponse(BaseModel):
    user_message: Message
    assistant_message: Message


class HealthCheck(BaseModel):
    status: Literal["ok", "error"]
    detail: str | None = None


class LlmHealthCheck(HealthCheck):
    model: str
    model_available: bool


class OcrHealthCheck(BaseModel):
    status: Literal["ok", "error", "disabled"]
    detail: str | None = None
    languages: list[str] | None = None


class HealthChecks(BaseModel):
    database: HealthCheck
    llm: LlmHealthCheck
    ocr: OcrHealthCheck


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    checks: HealthChecks


class ErrorDetail(BaseModel):
    field: str
    issue: str


class ErrorBody(BaseModel):
    code: str
    message: str
    correlation_id: str
    details: list[ErrorDetail] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
