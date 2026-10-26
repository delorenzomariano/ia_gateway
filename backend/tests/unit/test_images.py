"""Validación, preprocesamiento y coordinación del OCR de imágenes (chat/images.py)."""

import asyncio
import base64

import pytest
from PIL import Image

from ia_gateway.chat.images import (
    ImageInvalidError,
    ImageNoTextError,
    ImageReader,
    ImageTooLargeError,
    clean_ocr_text,
    decode_base64,
    has_text,
    open_image,
    preprocess,
    sanitize_filename,
)
from ia_gateway.config import Settings
from ia_gateway.ocr.base import OcrTimeoutError, OcrUnavailableError

from ..fakes import FakeOcrEngine
from ..images import (
    b64,
    blank_png,
    fake_png_bytes,
    gif_image,
    huge_pixels_png,
    jpeg_with_exif_rotation,
    jpeg_with_text,
    png_rgba_transparent,
    png_with_text,
    webp_with_text,
)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(_env_file=None, database_path=str(tmp_path / "x.db"))


# --- base64 y tamaño ------------------------------------------------------------------


def test_decode_base64_roundtrip():
    data = png_with_text()
    assert decode_base64(b64(data), max_bytes=10_000_000) == data


@pytest.mark.parametrize("value", ["no es base64!!", "data:image/png;base64,iVBORw0KGgo=", "===="])
def test_decode_base64_rejects_invalid(value):
    with pytest.raises(ImageInvalidError):
        decode_base64(value, max_bytes=10_000_000)


def test_decode_base64_rejects_empty():
    with pytest.raises(ImageInvalidError):
        decode_base64("", max_bytes=100)


def test_decode_base64_rejects_too_large():
    data = base64.b64encode(b"x" * 101).decode()
    with pytest.raises(ImageTooLargeError):
        decode_base64(data, max_bytes=100)
    assert decode_base64(base64.b64encode(b"x" * 100).decode(), max_bytes=100) == b"x" * 100


# --- formato real ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "media_type"),
    [
        (png_with_text(), "image/png"),
        (jpeg_with_text(), "image/jpeg"),
        (webp_with_text(), "image/webp"),
    ],
)
def test_open_image_accepts_supported_formats(data, media_type):
    image = open_image(data, media_type, max_pixels=25_000_000)
    assert image.size == (800, 200)


def test_open_image_rejects_declared_type_mismatch():
    with pytest.raises(ImageInvalidError):
        open_image(png_with_text(), "image/jpeg", max_pixels=25_000_000)


@pytest.mark.parametrize("data", [fake_png_bytes(), gif_image(), png_with_text()[:60]])
def test_open_image_rejects_fake_unsupported_or_damaged(data):
    with pytest.raises(ImageInvalidError):
        open_image(data, "image/png", max_pixels=25_000_000)


def test_open_image_rejects_too_many_pixels_without_decoding(monkeypatch):
    data = huge_pixels_png()
    loaded = []
    original_load = Image.Image.load
    monkeypatch.setattr(Image.Image, "load", lambda self: loaded.append(1) or original_load(self))
    with pytest.raises(ImageInvalidError):
        open_image(data, "image/png", max_pixels=25_000_000)
    assert loaded == []


# --- preprocesamiento -----------------------------------------------------------------


def _open(data: bytes) -> Image.Image:
    image = Image.open(__import__("io").BytesIO(data))
    image.load()
    return image


def test_preprocess_applies_exif_rotation_and_upscales_narrow_images():
    # 1200x400 con orientación 6 → 400x1200; ancho < 1000 → ×2
    result = preprocess(_open(jpeg_with_exif_rotation()))
    assert result.size == (800, 2400)
    assert result.mode == "L"


def test_preprocess_flattens_transparency_on_white():
    result = preprocess(_open(png_rgba_transparent()))
    assert result.mode == "L"
    assert result.getpixel((600, 200)) == 255  # fondo transparente → blanco
    assert result.getpixel((50, 50)) == 0  # rectángulo opaco negro


def test_preprocess_downscales_large_images():
    result = preprocess(Image.new("RGB", (8000, 2000), "white"))
    assert result.size == (4000, 1000)


def test_preprocess_keeps_medium_images():
    result = preprocess(Image.new("RGB", (1500, 900), "white"))
    assert result.size == (1500, 900)


# --- nombre y texto -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("captura.png", "captura.png"),
        ("C:\\fotos\\a.png", "a.png"),
        ("../x/b.png", "b.png"),
        ("c\x00a\x1fp.png", "cap.png"),
        ("   ", "imagen"),
        ("dir/", "imagen"),
    ],
)
def test_sanitize_filename(name, expected):
    assert sanitize_filename(name) == expected


def test_sanitize_filename_limits_length():
    assert len(sanitize_filename("a" * 300 + ".png")) == 255


def test_clean_ocr_text_normalizes_whitespace_and_control_chars():
    raw = "Hola\x07   mundo\t\tcruel\n\n\n\nSegundo   párrafo  \n"
    assert clean_ocr_text(raw, max_chars=1000) == ("Hola mundo cruel\n\nSegundo párrafo", False)


def test_clean_ocr_text_truncates():
    text, truncated = clean_ocr_text("abcdef " * 10, max_chars=10)
    assert len(text) <= 10
    assert truncated is True


@pytest.mark.parametrize(("text", "expected"), [("ab", False), ("··· -- ··", False), ("a1b", True)])
def test_has_text_requires_three_alphanumeric(text, expected):
    assert has_text(text) is expected


# --- ImageReader ------------------------------------------------------------------------


class Input:
    def __init__(self, data: bytes, filename="captura.png", media_type="image/png"):
        self.filename = filename
        self.media_type = media_type
        self.data = b64(data)


async def test_reader_returns_attachment(settings):
    engine = FakeOcrEngine(default="Hola   mundo")
    attachment = await ImageReader(settings, engine).read(Input(png_with_text()))
    assert attachment.text == "Hola mundo"
    assert attachment.truncated is False
    assert (attachment.filename, attachment.media_type) == ("captura.png", "image/png")
    assert (attachment.width, attachment.height) == (800, 200)
    assert attachment.size_bytes == len(png_with_text())
    # El motor recibe la imagen preprocesada (escala de grises, ampliada ×2).
    assert engine.images == [((1600, 400), "L")]


async def test_reader_truncates_long_text(settings):
    settings = settings.model_copy(update={"ocr_max_text_chars": 20})
    engine = FakeOcrEngine(default="palabra " * 50)
    attachment = await ImageReader(settings, engine).read(Input(png_with_text()))
    assert len(attachment.text) <= 20
    assert attachment.truncated is True


async def test_reader_rejects_images_without_text(settings):
    engine = FakeOcrEngine(default=" · ")
    with pytest.raises(ImageNoTextError):
        await ImageReader(settings, engine).read(Input(blank_png()))


async def test_reader_disabled_does_not_touch_the_engine(settings):
    engine = FakeOcrEngine()
    reader = ImageReader(settings.model_copy(update={"ocr_enabled": False}), engine)
    with pytest.raises(OcrUnavailableError):
        await reader.read(Input(png_with_text()))
    assert engine.calls == 0


async def test_reader_timeout(settings):
    settings = settings.model_copy(update={"ocr_timeout_s": 0.05})
    engine = FakeOcrEngine(delay_s=1)
    with pytest.raises(OcrTimeoutError):
        await ImageReader(settings, engine).read(Input(png_with_text()))


async def test_reader_validates_before_ocr(settings):
    engine = FakeOcrEngine()
    with pytest.raises(ImageInvalidError):
        await ImageReader(settings, engine).read(Input(fake_png_bytes()))
    assert engine.calls == 0


async def test_reader_limits_concurrency(settings):
    settings = settings.model_copy(update={"ocr_max_concurrency": 1})
    engine = FakeOcrEngine(delay_s=0.2)
    reader = ImageReader(settings, engine)
    loop = asyncio.get_running_loop()
    start = loop.time()
    await asyncio.gather(*(reader.read(Input(png_with_text())) for _ in range(3)))
    # Con un solo lugar, los tres reconocimientos van en serie.
    assert loop.time() - start >= 0.55
