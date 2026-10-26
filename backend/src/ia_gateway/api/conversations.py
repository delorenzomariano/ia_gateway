"""Endpoints de conversaciones y mensajes (contracts/openapi.yaml)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse

from ia_gateway.api.errors import ApiError, ErrorCode, error_body
from ia_gateway.api.router import error_responses
from ia_gateway.api.schemas import (
    Conversation,
    ConversationWithMessages,
    Message,
    SendMessageRequest,
    SendMessageResponse,
)
from ia_gateway.api.sse import PING, format_event, with_pings
from ia_gateway.chat.images import ImageInvalidError, ImageNoTextError, ImageTooLargeError
from ia_gateway.chat.locks import GenerationInProgressError
from ia_gateway.chat.orchestrator import (
    ConversationNotFoundError,
    DeltaEvent,
    EndEvent,
    ErrorEvent,
    Generation,
    NothingToRetryError,
    StartEvent,
)
from ia_gateway.main_deps import Services, get_services
from ia_gateway.ocr.base import OcrError, OcrTimeoutError
from ia_gateway.storage.repository import MessageRecord, NewAttachment

router = APIRouter(prefix="/conversations", tags=["conversations"])

ServicesDep = Annotated[Services, Depends(get_services)]

E = ErrorCode
LLM_ERRORS = (E.LLM_INVALID_RESPONSE, E.LLM_UNAVAILABLE, E.LLM_TIMEOUT)
IMAGE_ERRORS = (
    E.IMAGE_INVALID,
    E.IMAGE_TOO_LARGE,
    E.IMAGE_NO_TEXT,
    E.OCR_UNAVAILABLE,
    E.OCR_TIMEOUT,
)


def _visible(messages: list[MessageRecord]) -> list[Message]:
    return [
        Message.from_record(m)
        for m in messages
        if m.role in ("user", "assistant") and not m.tool_calls
    ]


async def _require_conversation(services: Services, conversation_id: str):
    conversation = await services.repository.get_conversation(conversation_id)
    if conversation is None:
        raise ApiError(E.CONVERSATION_NOT_FOUND)
    return conversation


@router.post(
    "",
    status_code=201,
    operation_id="createConversation",
    responses=error_responses(E.ACCESS_DENIED, E.INTERNAL_ERROR),
)
async def create_conversation(services: ServicesDep) -> Conversation:
    return Conversation.from_record(await services.repository.create_conversation())


@router.get(
    "/{conversation_id}",
    operation_id="getConversation",
    responses=error_responses(E.ACCESS_DENIED, E.CONVERSATION_NOT_FOUND, E.INTERNAL_ERROR),
)
async def get_conversation(conversation_id: str, services: ServicesDep) -> ConversationWithMessages:
    conversation = await _require_conversation(services, conversation_id)
    messages = await services.repository.list_messages(conversation_id)
    return ConversationWithMessages(
        **Conversation.from_record(conversation).model_dump(),
        generation_in_progress=services.locks.is_busy(conversation_id),
        messages=_visible(messages),
    )


@router.delete(
    "/{conversation_id}",
    status_code=204,
    response_class=Response,
    operation_id="deleteConversation",
    responses=error_responses(E.ACCESS_DENIED, E.GENERATION_IN_PROGRESS, E.INTERNAL_ERROR),
)
async def delete_conversation(conversation_id: str, services: ServicesDep) -> Response:
    if services.locks.is_busy(conversation_id):
        raise ApiError(E.GENERATION_IN_PROGRESS)
    await services.repository.delete_conversation(conversation_id)
    return Response(status_code=204)


def _validate_length(services: Services, content: str) -> None:
    limit = services.settings.max_message_chars
    if len(content) > limit:
        raise ApiError(
            E.VALIDATION_ERROR,
            f"El mensaje supera el máximo de {limit} caracteres.",
            details=[{"field": "content", "issue": f"máximo {limit} caracteres"}],
        )


async def _start(starter, *args) -> Generation:
    try:
        return await starter(*args)
    except ConversationNotFoundError as exc:
        raise ApiError(E.CONVERSATION_NOT_FOUND) from exc
    except GenerationInProgressError as exc:
        raise ApiError(E.GENERATION_IN_PROGRESS) from exc
    except NothingToRetryError as exc:
        raise ApiError(E.NOTHING_TO_RETRY) from exc


async def _read_image(
    services: Services, conversation_id: str, body: SendMessageRequest
) -> NewAttachment | None:
    """Reconoce el texto de la imagen antes de iniciar la respuesta (research.md R4).

    Primero se descartan los casos que igual fallarían (404/409) para no gastar OCR en ellos;
    `start_send` vuelve a tomar el lock de forma atómica.
    """
    if body.image is None:
        return None
    await _require_conversation(services, conversation_id)
    if services.locks.is_busy(conversation_id):
        raise ApiError(E.GENERATION_IN_PROGRESS)
    try:
        return await services.image_reader.read(body.image)
    except ImageInvalidError as exc:
        raise ApiError(E.IMAGE_INVALID) from exc
    except ImageTooLargeError as exc:
        raise ApiError(E.IMAGE_TOO_LARGE) from exc
    except ImageNoTextError as exc:
        raise ApiError(E.IMAGE_NO_TEXT) from exc
    except OcrTimeoutError as exc:
        raise ApiError(E.OCR_TIMEOUT) from exc
    except OcrError as exc:
        raise ApiError(E.OCR_UNAVAILABLE) from exc


def _wants_stream(request: Request) -> bool:
    return "text/event-stream" in request.headers.get("accept", "")


def _respond_stream(generation: Generation, ping_interval: float) -> StreamingResponse:
    async def body():
        async for event in with_pings(generation.events(), ping_interval):
            if event is PING:
                yield format_event("ping", {})
            elif isinstance(event, StartEvent):
                yield format_event(
                    "message.start",
                    {
                        "user_message": _message_json(event.user_message),
                        "assistant_message_id": event.assistant_message_id,
                    },
                )
            elif isinstance(event, DeltaEvent):
                yield format_event("delta", {"text": event.text})
            elif isinstance(event, EndEvent):
                yield format_event(
                    "message.end", {"assistant_message": _message_json(event.assistant_message)}
                )
            elif isinstance(event, ErrorEvent):
                assistant = event.assistant_message
                yield format_event(
                    "error",
                    {
                        **error_body(ErrorCode(event.code)),
                        "assistant_message": _message_json(assistant) if assistant else None,
                    },
                )

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _message_json(record: MessageRecord) -> dict:
    return Message.from_record(record).model_dump(mode="json")


async def _respond_json(generation: Generation) -> SendMessageResponse:
    assistant: MessageRecord | None = None
    async for event in generation.events():
        if isinstance(event, EndEvent):
            assistant = event.assistant_message
        elif isinstance(event, ErrorEvent):
            raise ApiError(ErrorCode(event.code))
    if assistant is None:
        raise ApiError(E.INTERNAL_ERROR)
    return SendMessageResponse(
        user_message=Message.from_record(generation.user_message),
        assistant_message=Message.from_record(assistant),
    )


@router.post(
    "/{conversation_id}/messages",
    operation_id="sendMessage",
    response_model=SendMessageResponse,
    responses={
        200: {
            "description": "Respuesta del asistente (JSON o stream SSE según `Accept`)",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        },
        **error_responses(
            E.ACCESS_DENIED,
            E.CONVERSATION_NOT_FOUND,
            E.GENERATION_IN_PROGRESS,
            E.VALIDATION_ERROR,
            *IMAGE_ERRORS,
            *LLM_ERRORS,
            E.INTERNAL_ERROR,
        ),
    },
)
async def send_message(
    conversation_id: str, body: SendMessageRequest, request: Request, services: ServicesDep
) -> SendMessageResponse | StreamingResponse:
    _validate_length(services, body.content)
    attachment = await _read_image(services, conversation_id, body)
    generation = await _start(
        services.orchestrator.start_send, conversation_id, body.content, attachment
    )
    return await _respond(request, services, generation)


@router.post(
    "/{conversation_id}/messages/retry",
    operation_id="retryLastMessage",
    response_model=SendMessageResponse,
    responses={
        200: {
            "description": "Respuesta regenerada (JSON o stream SSE según `Accept`)",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        },
        **error_responses(
            E.ACCESS_DENIED,
            E.CONVERSATION_NOT_FOUND,
            E.GENERATION_IN_PROGRESS,
            E.NOTHING_TO_RETRY,
            *LLM_ERRORS,
            E.INTERNAL_ERROR,
        ),
    },
)
async def retry_last_message(
    conversation_id: str, request: Request, services: ServicesDep
) -> SendMessageResponse | StreamingResponse:
    generation = await _start(services.orchestrator.start_retry, conversation_id)
    return await _respond(request, services, generation)


async def _respond(
    request: Request, services: Services, generation: Generation
) -> SendMessageResponse | StreamingResponse:
    if _wants_stream(request):
        return _respond_stream(generation, services.settings.sse_ping_interval_s)
    return await _respond_json(generation)
