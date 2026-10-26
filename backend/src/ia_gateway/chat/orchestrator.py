"""Orquestación de una respuesta: mensaje → contexto → modelo → respuesta guardada."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

import anyio

from ia_gateway.chat.context import build_context
from ia_gateway.chat.locks import GenerationLocks
from ia_gateway.chat.validation import StreamSanitizer, sanitize_llm_text
from ia_gateway.config import Settings
from ia_gateway.llm.base import (
    LLMClient,
    LLMInvalidResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
    ToolCall,
)
from ia_gateway.observability.logging import log_content
from ia_gateway.storage.repository import (
    ConversationRepository,
    MessageRecord,
    NewAttachment,
    NewMessage,
    NewToolInvocation,
)
from ia_gateway.tools.registry import ToolRegistry

logger = logging.getLogger("ia_gateway.chat")


class ConversationNotFoundError(Exception):
    pass


class NothingToRetryError(Exception):
    pass


# Códigos de error guardados en el mensaje y devueltos por la API (contracts/openapi.yaml).
ERROR_CODES: dict[type[Exception], str] = {
    LLMUnavailableError: "LLM_UNAVAILABLE",
    LLMTimeoutError: "LLM_TIMEOUT",
    LLMInvalidResponseError: "LLM_INVALID_RESPONSE",
}
INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True)
class StartEvent:
    user_message: MessageRecord
    assistant_message_id: str


@dataclass(frozen=True)
class DeltaEvent:
    text: str


@dataclass(frozen=True)
class EndEvent:
    assistant_message: MessageRecord


@dataclass(frozen=True)
class ErrorEvent:
    code: str
    assistant_message: MessageRecord | None


ChatEvent = StartEvent | DeltaEvent | EndEvent | ErrorEvent


class ChatOrchestrator:
    def __init__(
        self,
        settings: Settings,
        repository: ConversationRepository,
        llm: LLMClient,
        locks: GenerationLocks,
        tools: ToolRegistry | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.llm = llm
        self.locks = locks
        self.tools = tools or ToolRegistry()

    async def start_send(
        self, conversation_id: str, content: str, attachment: NewAttachment | None = None
    ) -> Generation:
        """Valida, toma el lock y guarda el mensaje del usuario antes de llamar al modelo.

        Lanza ConversationNotFoundError o GenerationInProgressError antes de iniciar la
        respuesta, para que la API pueda devolverlos como errores HTTP normales. El adjunto
        (texto ya reconocido de una imagen) se guarda junto con el mensaje.
        """
        if await self.repository.get_conversation(conversation_id) is None:
            raise ConversationNotFoundError(conversation_id)
        release = self.locks.acquire(conversation_id)
        try:
            user_message = await self.repository.add_message(
                conversation_id, NewMessage(role="user", content=content), attachment=attachment
            )
        except BaseException:
            release()
            raise
        return Generation(self, conversation_id, user_message, release)

    async def start_retry(self, conversation_id: str) -> Generation:
        """Regenera la respuesta al último mensaje del usuario sin duplicarlo.

        Válido si el último mensaje visible es del usuario o una respuesta con estado `error`
        (que se descarta); si no, NothingToRetryError.
        """
        if await self.repository.get_conversation(conversation_id) is None:
            raise ConversationNotFoundError(conversation_id)
        release = self.locks.acquire(conversation_id)
        try:
            visible = [
                m
                for m in await self.repository.list_messages(conversation_id)
                if m.role in ("user", "assistant") and not m.tool_calls
            ]
            if not visible:
                raise NothingToRetryError(conversation_id)
            last = visible[-1]
            if last.role == "assistant" and last.status == "error":
                await self.repository.delete_message(last.id)
                last = visible[-2] if len(visible) > 1 else None
            elif last.role != "user":
                raise NothingToRetryError(conversation_id)
            if last is None or last.role != "user":
                raise NothingToRetryError(conversation_id)
        except BaseException:
            release()
            raise
        return Generation(self, conversation_id, last, release)


class Generation:
    """Una respuesta en curso. El lock ya está tomado; `events()` se itera una sola vez."""

    def __init__(
        self,
        orchestrator: ChatOrchestrator,
        conversation_id: str,
        user_message: MessageRecord,
        release: Callable[[], None],
    ) -> None:
        self._o = orchestrator
        self.conversation_id = conversation_id
        self.user_message = user_message
        self.assistant_message_id = str(uuid.uuid4())
        self._release = release

    async def events(self) -> AsyncIterator[ChatEvent]:
        o = self._o
        started = time.perf_counter()
        first_chunk_ms: float | None = None
        prompt_tokens = completion_tokens = None
        sanitizer = StreamSanitizer()
        try:
            yield StartEvent(self.user_message, self.assistant_message_id)

            specs = o.tools.to_tool_specs() if o.tools else []
            tool_rounds = 0
            while True:
                # Tras MAX_TOOL_ROUNDS rondas ya no se ofrecen herramientas: el modelo debe
                # responder con texto.
                offer = specs if specs and tool_rounds < o.settings.max_tool_rounds else None
                history = await o.repository.list_messages(self.conversation_id)
                context = build_context(
                    o.settings.system_prompt, history, o.settings.context_char_budget
                )
                tool_calls: list[ToolCall] = []
                async for chunk in o.llm.chat_stream(context, offer):
                    if chunk.text:
                        if first_chunk_ms is None:
                            first_chunk_ms = (time.perf_counter() - started) * 1000
                        visible = sanitizer.feed(chunk.text)
                        if visible:
                            yield DeltaEvent(visible)
                    tool_calls.extend(chunk.tool_calls)
                    if chunk.done:
                        prompt_tokens = _add(prompt_tokens, chunk.prompt_tokens)
                        completion_tokens = _add(completion_tokens, chunk.completion_tokens)
                if not tool_calls or offer is None:
                    break
                tool_rounds += 1
                await self._run_tools(tool_calls)

            # La respuesta final debe tener texto aunque haya habido llamadas a herramientas.
            content = sanitize_llm_text(sanitizer.text)
            assistant = await o.repository.add_message(
                self.conversation_id,
                NewMessage(
                    id=self.assistant_message_id,
                    role="assistant",
                    content=content,
                    model=o.llm.model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                ),
            )
            logger.info(
                "chat_completed",
                extra={
                    "conversation_id": self.conversation_id,
                    "model": o.llm.model,
                    "first_chunk_ms": _round(first_chunk_ms),
                    "total_ms": _round((time.perf_counter() - started) * 1000),
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    **log_content("user_text", self.user_message.content),
                    **log_content("assistant_text", content),
                },
            )
            yield EndEvent(assistant)
        except Exception as exc:
            code = ERROR_CODES.get(type(exc), INTERNAL_ERROR)
            if code == INTERNAL_ERROR:
                logger.exception("chat_failed", extra={"conversation_id": self.conversation_id})
            else:
                logger.warning(
                    "chat_failed",
                    extra={
                        "conversation_id": self.conversation_id,
                        "error_code": code,
                        "error": str(exc),
                        "total_ms": _round((time.perf_counter() - started) * 1000),
                    },
                )
            yield ErrorEvent(code, await self._save_error(code))
        except (asyncio.CancelledError, GeneratorExit):
            # El cliente canceló o se desconectó: se guarda lo generado hasta ahora.
            with anyio.CancelScope(shield=True):
                await self._save_incomplete(sanitizer.text)
            raise
        finally:
            self._release()

    async def _run_tools(self, calls: list[ToolCall]) -> None:
        """Guarda la solicitud del modelo, ejecuta cada herramienta y guarda sus resultados."""
        o = self._o
        request = await o.repository.add_message(
            self.conversation_id,
            NewMessage(
                role="assistant",
                content="",
                tool_calls=[{"name": c.name, "arguments": c.arguments} for c in calls],
                model=o.llm.model,
            ),
        )
        for call in calls:
            result = await o.tools.execute(call.name, call.arguments)
            await o.repository.add_tool_invocation(
                self.conversation_id,
                NewToolInvocation(
                    assistant_message_id=request.id,
                    tool_name=call.name,
                    arguments=call.arguments,
                    status=result.status,
                    duration_ms=result.duration_ms,
                    result=result.output,
                    error=result.error,
                ),
            )
            await o.repository.add_message(
                self.conversation_id,
                NewMessage(role="tool", content=result.for_model(), tool_name=call.name),
            )
            logger.info(
                "tool_invoked",
                extra={
                    "conversation_id": self.conversation_id,
                    "tool": call.name,
                    "status": result.status,
                    "duration_ms": result.duration_ms,
                },
            )

    async def _save_error(self, code: str) -> MessageRecord | None:
        try:
            return await self._o.repository.add_message(
                self.conversation_id,
                NewMessage(
                    id=self.assistant_message_id,
                    role="assistant",
                    content="",
                    status="error",
                    error_code=code,
                    model=self._o.llm.model,
                ),
            )
        except Exception:
            logger.exception("save_error_message_failed")
            return None

    async def _save_incomplete(self, text: str) -> None:
        o = self._o
        if text:
            await o.repository.add_message(
                self.conversation_id,
                NewMessage(
                    id=self.assistant_message_id,
                    role="assistant",
                    content=text,
                    status="incomplete",
                    model=o.llm.model,
                ),
            )
        logger.info(
            "chat_cancelled",
            extra={"conversation_id": self.conversation_id, "saved_chars": len(text)},
        )


def _add(total: int | None, value: int | None) -> int | None:
    if value is None:
        return total
    return (total or 0) + value


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 1)
