"""Interfaz del motor de reconocimiento de texto (OCR), independiente del proveedor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from PIL import Image


@dataclass(frozen=True)
class OcrResult:
    text: str
    word_count: int = 0
    dropped_words: int = 0
    duration_ms: int = 0


@dataclass(frozen=True)
class OcrHealth:
    ok: bool
    detail: str | None = None
    languages: list[str] = field(default_factory=list)


class OcrError(Exception):
    """Falla del motor de OCR."""


class OcrUnavailableError(OcrError):
    """El motor no está instalado, no responde o le faltan los idiomas configurados."""


class OcrTimeoutError(OcrError):
    """El reconocimiento superó el tiempo máximo."""


class OcrFailedError(OcrError):
    """Cualquier otra falla del motor."""


class OcrEngine(Protocol):
    def recognize(self, image: Image.Image, *, timeout_s: float) -> OcrResult:
        """Reconoce el texto de una imagen ya preprocesada.

        Es síncrono (bloquea): se ejecuta en un hilo. Debe respetar `timeout_s` y lanzar
        `OcrTimeoutError` si lo supera.
        """
        ...

    async def health(self) -> OcrHealth: ...
