"""Pruebas contra Tesseract real (excluidas por defecto): `uv run pytest -m tesseract -s`.

Usan IA_GATEWAY_OCR_TESSERACT_CMD / IA_GATEWAY_OCR_LANGUAGES del entorno (o `.env`); se
saltean si Tesseract no está instalado. No llaman a Ollama.
"""

import io
import random
import shutil
import statistics
import time

import pytest
from PIL import Image, ImageDraw

from ia_gateway.chat.images import ImageNoTextError, ImageReader
from ia_gateway.config import Settings
from ia_gateway.ocr.tesseract import TesseractOcrEngine

from ..images import b64, blank_png, png_with_text, text_font

pytestmark = pytest.mark.tesseract


@pytest.fixture(scope="module")
def settings() -> Settings:
    settings = Settings()
    command = settings.ocr_tesseract_cmd or shutil.which("tesseract")
    if not command or not shutil.which(command):
        pytest.skip(
            "Tesseract no está instalado: ver specs/002-chat-image-ocr/quickstart.md (sección 1) "
            "o configurar IA_GATEWAY_OCR_TESSERACT_CMD"
        )
    return settings


@pytest.fixture
def reader(settings) -> ImageReader:
    return ImageReader(settings, TesseractOcrEngine(settings))


class Input:
    def __init__(self, data: bytes, filename="prueba.png", media_type="image/png"):
        self.filename, self.media_type, self.data = filename, media_type, b64(data)


async def test_health_reports_languages(settings):
    health = await TesseractOcrEngine(settings).health()
    assert health.ok, health.detail
    assert {"spa", "eng"} <= set(health.languages)


@pytest.mark.parametrize("text", ["Hola mundo, ¿cómo están?", "Hello world from Tesseract"])
async def test_recognizes_spanish_and_english(reader, text):
    attachment = await reader.read(Input(png_with_text(text, size=(1400, 200), font_size=48)))
    normalized = attachment.text.lower()
    for word in text.lower().replace(",", "").replace("¿", "").replace("?", "").split():
        assert word in normalized, f"falta {word!r} en {attachment.text!r}"


async def test_blank_image_has_no_text(reader):
    with pytest.raises(ImageNoTextError):
        await reader.read(Input(blank_png()))


def _document_jpeg(seed: int, target_bytes: int = 2_000_000) -> bytes:
    """Página con varias líneas de texto y algo de ruido, de ~2 MB en JPEG."""
    rng = random.Random(seed)
    image = Image.new("RGB", (2480, 3508), "white")  # A4 a 300 dpi
    draw = ImageDraw.Draw(image)
    font = text_font(40)
    words = "factura pedido cliente importe total fecha número envío dirección".split()
    for row in range(40):
        line = " ".join(rng.choice(words) for _ in range(8))
        draw.text((150, 150 + row * 80), f"{row + 1}. {line}", fill="black", font=font)
    noise = Image.effect_noise(image.size, 24).convert("RGB")
    image = Image.blend(image, noise, 0.12)
    for quality in (95, 90, 85, 80, 70):
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality)
        if buffer.tell() <= target_bytes * 1.2:
            break
    return buffer.getvalue()


async def test_sc002_recognition_time(reader, capsys):
    """SC-002: p90 del reconocimiento < 10 s para imágenes de ~2 MB (se informa la medición)."""
    durations: list[float] = []
    sizes: list[int] = []
    for seed in range(10):
        data = _document_jpeg(seed)
        sizes.append(len(data))
        started = time.perf_counter()
        attachment = await reader.read(Input(data, "pagina.jpg", "image/jpeg"))
        durations.append(time.perf_counter() - started)
        assert "factura" in attachment.text.lower() or "pedido" in attachment.text.lower()

    p90 = statistics.quantiles(durations, n=10)[-1]
    with capsys.disabled():
        print(
            f"\nSC-002 OCR (s): {[round(d, 2) for d in durations]} | p90={p90:.2f} | "
            f"tamaños (MB): {[round(s / 1e6, 2) for s in sizes]}"
        )
    assert p90 < 10, f"p90 del reconocimiento = {p90:.2f} s (meta < 10 s)"
