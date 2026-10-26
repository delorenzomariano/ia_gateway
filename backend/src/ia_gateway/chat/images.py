"""Imágenes adjuntas: validación, preprocesamiento y reconocimiento de texto (research.md R2–R6).

La imagen solo vive en memoria durante el reconocimiento; se guardan los metadatos y el texto.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import io
import logging
import re
import threading
import time
import warnings
from dataclasses import dataclass
from typing import Protocol

from PIL import Image, ImageOps

from ia_gateway.chat.validation import remove_control_chars
from ia_gateway.config import Settings
from ia_gateway.observability.logging import log_content
from ia_gateway.ocr.base import OcrEngine, OcrError, OcrTimeoutError, OcrUnavailableError
from ia_gateway.storage.repository import ImageMediaType, NewAttachment

logger = logging.getLogger("ia_gateway.ocr")

FORMATS: dict[str, str] = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}
MAX_SIDE = 4000
UPSCALE_BELOW_WIDTH = 1000
MIN_ALNUM_CHARS = 3
# Margen sobre el timeout del motor antes de dar por perdido el hilo (el motor corta primero).
TIMEOUT_GRACE_S = 5


class ImageInvalidError(Exception):
    pass


class ImageTooLargeError(Exception):
    pass


class ImageNoTextError(Exception):
    pass


class ImageInputLike(Protocol):
    filename: str
    media_type: str
    data: str


# --- funciones puras --------------------------------------------------------------------


def decode_base64(data: str, max_bytes: int) -> bytes:
    if data.startswith("data:"):
        raise ImageInvalidError("se esperaba base64 sin prefijo data:")
    # Estimación barata antes de decodificar: base64 ocupa 4/3 del tamaño original.
    if len(data) // 4 * 3 > max_bytes + 3:
        raise ImageTooLargeError(f"más de {max_bytes} bytes")
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ImageInvalidError("base64 inválido") from exc
    if not raw:
        raise ImageInvalidError("imagen vacía")
    if len(raw) > max_bytes:
        raise ImageTooLargeError(f"más de {max_bytes} bytes")
    return raw


def open_image(data: bytes, media_type: str, max_pixels: int) -> Image.Image:
    """Abre la imagen verificando su formato real, sus píxeles y su integridad."""
    expected = FORMATS.get(media_type)
    if expected is None:
        raise ImageInvalidError(f"tipo no admitido: {media_type}")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            probe = Image.open(io.BytesIO(data))
            if probe.format != expected:
                raise ImageInvalidError(f"el contenido es {probe.format}, no {expected}")
            width, height = probe.size
            if width * height > max_pixels:
                raise ImageInvalidError(f"{width}x{height} supera {max_pixels} píxeles")
            probe.verify()  # deja la imagen inutilizable: hay que volver a abrirla
            image = Image.open(io.BytesIO(data))
            image.load()
    except ImageInvalidError:
        raise
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError, Warning) as exc:
        raise ImageInvalidError(f"imagen dañada o no reconocida: {exc}") from exc
    return image


def preprocess(image: Image.Image) -> Image.Image:
    """Orientación EXIF, fondo blanco bajo la transparencia, escala de grises y tamaño útil."""
    image = ImageOps.exif_transpose(image)
    if image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        image = Image.alpha_composite(background, rgba)
    image = image.convert("L")
    width, height = image.size
    if max(width, height) > MAX_SIDE:
        scale = MAX_SIDE / max(width, height)
        image = image.resize(
            (max(1, round(width * scale)), max(1, round(height * scale))), Image.Resampling.LANCZOS
        )
    elif width < UPSCALE_BELOW_WIDTH and max(width, height) * 2 <= MAX_SIDE:
        image = image.resize((width * 2, height * 2), Image.Resampling.LANCZOS)
    return image


def sanitize_filename(name: str) -> str:
    base = re.split(r"[\\/]", name)[-1]
    base = remove_control_chars(base).replace("\n", "").replace("\t", "").strip()
    return base[:255] or "imagen"


_SPACES = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def clean_ocr_text(text: str, max_chars: int) -> tuple[str, bool]:
    lines = [_SPACES.sub(" ", line).strip() for line in remove_control_chars(text).split("\n")]
    cleaned = _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()
    if len(cleaned) <= max_chars:
        return cleaned, False
    return cleaned[:max_chars].rstrip(), True


def has_text(text: str) -> bool:
    return sum(ch.isalnum() for ch in text) >= MIN_ALNUM_CHARS


# --- coordinación -----------------------------------------------------------------------


class ImageReader:
    """Valida la imagen y reconoce su texto con concurrencia y tiempo acotados."""

    def __init__(self, settings: Settings, engine: OcrEngine) -> None:
        self.settings = settings
        self.engine = engine
        self._slots = asyncio.Semaphore(settings.ocr_max_concurrency)

    async def read(self, image: ImageInputLike) -> NewAttachment:
        s = self.settings
        if not s.ocr_enabled:
            raise OcrUnavailableError("el reconocimiento de imágenes está deshabilitado")
        started = time.perf_counter()
        meta: dict[str, object] = {"media_type": image.media_type}
        try:
            # En el hilo principal solo lo barato; decodificar con Pillow va en el hilo del OCR.
            data = decode_base64(image.data, s.ocr_max_image_bytes)
            meta["size_bytes"] = len(data)
            outcome = await self._recognize(data, image.media_type)
            meta.update(width=outcome.width, height=outcome.height)
            text, truncated = clean_ocr_text(outcome.text, s.ocr_max_text_chars)
            if not has_text(text):
                raise ImageNoTextError("no se reconoció texto legible")
        except (ImageInvalidError, ImageTooLargeError, ImageNoTextError, OcrError) as exc:
            logger.warning(
                "ocr_failed",
                extra={
                    **meta,
                    "error": type(exc).__name__,
                    "duration_ms": _ms(started),
                },
            )
            raise
        attachment = NewAttachment(
            filename=sanitize_filename(image.filename),
            media_type=_media_type(image.media_type),
            size_bytes=len(data),
            width=outcome.width,
            height=outcome.height,
            text=text,
            truncated=truncated,
            ocr_duration_ms=_ms(started),
        )
        logger.info(
            "ocr_completed",
            extra={
                **meta,
                "duration_ms": attachment.ocr_duration_ms,
                "engine_ms": outcome.engine_ms,
                "chars": len(text),
                "truncated": truncated,
                "words": outcome.word_count,
                "dropped_words": outcome.dropped_words,
                **log_content("ocr_text", text),
            },
        )
        return attachment

    async def _recognize(self, data: bytes, media_type: str) -> _Outcome:
        """Corre decodificación, preprocesamiento y OCR en un hilo.

        El lugar en la cola se libera recién cuando el hilo termina, aunque la espera se corte
        por timeout o porque el cliente se desconectó: así nunca hay más reconocimientos en
        paralelo que `ocr_max_concurrency`.
        """
        s = self.settings
        abandoned = threading.Event()

        def work() -> _Outcome:
            if abandoned.is_set():
                raise OcrTimeoutError("abandonado antes de empezar")
            original = open_image(data, media_type, s.ocr_max_pixels)
            prepared = preprocess(original)
            result = self.engine.recognize(prepared, timeout_s=s.ocr_timeout_s)
            return _Outcome(
                text=result.text,
                width=original.width,
                height=original.height,
                word_count=result.word_count,
                dropped_words=result.dropped_words,
                engine_ms=result.duration_ms,
            )

        await self._slots.acquire()
        future = asyncio.get_running_loop().run_in_executor(None, work)

        def finished(done: asyncio.Future) -> None:
            self._slots.release()
            if not done.cancelled():
                done.exception()  # marca la excepción como leída si nadie la esperó

        future.add_done_callback(finished)
        try:
            return await asyncio.wait_for(asyncio.shield(future), s.ocr_timeout_s + TIMEOUT_GRACE_S)
        except TimeoutError as exc:
            abandoned.set()
            raise OcrTimeoutError("el reconocimiento no terminó a tiempo") from exc
        except asyncio.CancelledError:
            abandoned.set()
            raise


@dataclass(frozen=True)
class _Outcome:
    text: str
    width: int
    height: int
    word_count: int
    dropped_words: int
    engine_ms: int


def _media_type(value: str) -> ImageMediaType:
    if value not in FORMATS:
        raise ImageInvalidError(f"tipo no admitido: {value}")
    return value  # type: ignore[return-value]


def _ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)
