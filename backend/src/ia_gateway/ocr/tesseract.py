"""Adaptador de OCR sobre Tesseract (pytesseract): único código que conoce su API."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import anyio.to_thread
import pytesseract

from ia_gateway.config import Settings
from ia_gateway.ocr.base import (
    OcrFailedError,
    OcrHealth,
    OcrResult,
    OcrTimeoutError,
    OcrUnavailableError,
)

if TYPE_CHECKING:
    from PIL import Image

# LSTM + segmentación automática de página (research.md R5).
TESSERACT_CONFIG = "--oem 1 --psm 3"
HEALTH_CACHE_S = 60


class TesseractOcrEngine:
    def __init__(self, settings: Settings) -> None:
        self.languages = settings.ocr_languages
        self.min_confidence = settings.ocr_min_confidence
        if settings.ocr_tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = settings.ocr_tesseract_cmd
        self._health: OcrHealth | None = None
        self._health_at = 0.0

    def recognize(self, image: Image.Image, *, timeout_s: float) -> OcrResult:
        started = time.perf_counter()
        try:
            data = pytesseract.image_to_data(
                image,
                lang=self.languages,
                config=TESSERACT_CONFIG,
                output_type=pytesseract.Output.DICT,
                timeout=timeout_s,
            )
        except pytesseract.TesseractNotFoundError as exc:
            raise OcrUnavailableError("Tesseract no está instalado") from exc
        except pytesseract.TesseractError as exc:
            if "language" in str(exc).lower():
                raise OcrUnavailableError("faltan los datos de idioma de Tesseract") from exc
            raise OcrFailedError(str(exc)) from exc
        except RuntimeError as exc:
            # pytesseract mata el proceso y lanza RuntimeError("Tesseract process timeout").
            if "timeout" in str(exc).lower():
                raise OcrTimeoutError(str(exc)) from exc
            raise OcrFailedError(str(exc)) from exc
        text, kept, dropped = _reconstruct(data, self.min_confidence)
        return OcrResult(
            text=text,
            word_count=kept,
            dropped_words=dropped,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )

    async def health(self) -> OcrHealth:
        now = time.monotonic()
        if self._health is None or now - self._health_at >= HEALTH_CACHE_S:
            self._health = await anyio.to_thread.run_sync(self._check)
            self._health_at = now
        return self._health

    def _check(self) -> OcrHealth:
        required = [lang for lang in self.languages.split("+") if lang]
        try:
            available = set(pytesseract.get_languages(config=""))
        except (pytesseract.TesseractNotFoundError, pytesseract.TesseractError, OSError):
            return OcrHealth(ok=False, detail="Tesseract no está instalado o no se encontró")
        present = [lang for lang in required if lang in available]
        missing = [lang for lang in required if lang not in available]
        if missing:
            detail = f"faltan los idiomas de Tesseract: {', '.join(missing)}"
            return OcrHealth(ok=False, detail=detail, languages=present)
        return OcrHealth(ok=True, languages=present)


def _reconstruct(data: dict[str, list[Any]], min_confidence: float) -> tuple[str, int, int]:
    """Arma el texto con las palabras confiables: una línea por línea de Tesseract y una línea
    en blanco entre párrafos o bloques."""
    paragraphs: list[list[tuple[int, int, int]]] = []
    lines: dict[tuple[int, int, int], list[str]] = {}
    current_paragraph: tuple[int, int] | None = None
    kept = dropped = 0

    for i, raw in enumerate(data["text"]):
        word = str(raw).strip()
        if not word:
            continue
        try:
            confidence = float(data["conf"][i])
        except (TypeError, ValueError):
            confidence = -1
        if confidence < min_confidence:
            dropped += 1
            continue
        kept += 1
        block, par, line = data["block_num"][i], data["par_num"][i], data["line_num"][i]
        if (block, par) != current_paragraph:
            current_paragraph = (block, par)
            paragraphs.append([])
        key = (block, par, line)
        if key not in lines:
            lines[key] = []
            paragraphs[-1].append(key)
        lines[key].append(word)

    text = "\n\n".join("\n".join(" ".join(lines[key]) for key in keys) for keys in paragraphs)
    return text, kept, dropped
