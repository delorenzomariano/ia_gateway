"""Dobles de prueba: modelo de lenguaje y motor de OCR programables (sin servicios reales)."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from ia_gateway.llm.base import ChatMessage, LLMChunk, LLMHealth, ToolCall, ToolSpec
from ia_gateway.ocr.base import OcrHealth, OcrResult, OcrTimeoutError


@dataclass
class Sleep:
    seconds: float


Step = LLMChunk | Exception | Sleep


def text_reply(*fragments: str, prompt_tokens: int = 7, completion_tokens: int = 5) -> list[Step]:
    steps: list[Step] = [LLMChunk(text=fragment) for fragment in fragments]
    steps.append(
        LLMChunk(done=True, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    )
    return steps


def tool_call_reply(name: str, arguments: dict | None = None) -> list[Step]:
    return [LLMChunk(tool_calls=[ToolCall(name=name, arguments=arguments or {})], done=True)]


@dataclass
class Call:
    messages: list[ChatMessage]
    tools: list[ToolSpec] | None


@dataclass
class FakeLLMClient:
    """Cada llamada a chat_stream consume el siguiente guion de `scripts`.

    Si no quedan guiones se usa `default`. Un `Exception` en el guion se lanza en ese punto;
    `Sleep` simula latencia (permite probar timeouts y cancelación).
    """

    model: str = "fake-model"
    scripts: list[list[Step]] = field(default_factory=list)
    default: list[Step] = field(default_factory=lambda: text_reply("Hola, ", "soy un asistente."))
    calls: list[Call] = field(default_factory=list)
    health_result: LLMHealth | None = None
    cancelled: int = 0
    closed: bool = False

    def queue(self, *scripts: list[Step]) -> None:
        self.scripts.extend(scripts)

    async def chat_stream(
        self, messages: list[ChatMessage], tools: list[ToolSpec] | None = None
    ) -> AsyncIterator[LLMChunk]:
        self.calls.append(Call(messages=list(messages), tools=tools))
        script = self.scripts.pop(0) if self.scripts else self.default
        try:
            for step in script:
                if isinstance(step, Sleep):
                    await asyncio.sleep(step.seconds)
                elif isinstance(step, Exception):
                    raise step
                else:
                    yield step
        except (asyncio.CancelledError, GeneratorExit):
            self.cancelled += 1
            raise

    async def health(self) -> LLMHealth:
        return self.health_result or LLMHealth(ok=True, model=self.model, model_available=True)

    async def aclose(self) -> None:
        self.closed = True


@dataclass
class FakeOcrEngine:
    """Motor de OCR programable. Cada `recognize` consume el siguiente resultado de la cola.

    Un `Exception` en la cola se lanza. `delay_s` simula la duración; si supera `timeout_s`,
    lanza `OcrTimeoutError` como lo hace pytesseract al matar el proceso.
    """

    default: str = "Texto reconocido de prueba"
    results: list[str | Exception] = field(default_factory=list)
    delay_s: float = 0
    calls: int = 0
    images: list[tuple[tuple[int, int], str]] = field(default_factory=list)
    health_result: OcrHealth = field(
        default_factory=lambda: OcrHealth(ok=True, languages=["eng", "spa"])
    )
    health_calls: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def queue_text(self, *texts: str) -> None:
        self.results.extend(texts)

    def queue_error(self, *errors: Exception) -> None:
        self.results.extend(errors)

    def recognize(self, image, *, timeout_s: float) -> OcrResult:
        with self._lock:
            self.calls += 1
            self.images.append((image.size, image.mode))
            result = self.results.pop(0) if self.results else self.default
        if self.delay_s:
            threading.Event().wait(min(self.delay_s, timeout_s))
            if self.delay_s > timeout_s:
                raise OcrTimeoutError("timeout")
        if isinstance(result, Exception):
            raise result
        return OcrResult(text=result, word_count=len(result.split()), duration_ms=1)

    async def health(self) -> OcrHealth:
        self.health_calls += 1
        return self.health_result
