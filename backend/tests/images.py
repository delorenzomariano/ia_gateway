"""Imágenes de prueba generadas en memoria con Pillow (sin binarios versionados)."""

from __future__ import annotations

import base64
import io

from PIL import Image, ImageDraw, ImageFont

# La fuente que trae Pillow no tiene "á", "ó" ni "¿" (los dibuja como cajas); para textos en
# español se prefiere una fuente del sistema.
_SYSTEM_FONTS = (
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
)


def text_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _SYSTEM_FONTS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _text_image(text: str, size: tuple[int, int], font_size: int, mode: str = "RGB") -> Image.Image:
    background = (255, 255, 255, 255) if mode == "RGBA" else "white"
    image = Image.new(mode, size, background)
    draw = ImageDraw.Draw(image)
    font = text_font(font_size)
    draw.multiline_text((20, 20), text, fill="black", font=font)
    return image


def _encode(image: Image.Image, fmt: str, **kwargs) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **kwargs)
    return buffer.getvalue()


def png_with_text(text: str = "Hola mundo", size=(800, 200), font_size: int = 36) -> bytes:
    return _encode(_text_image(text, size, font_size), "PNG")


def jpeg_with_text(text: str = "Hola mundo", size=(800, 200), font_size: int = 36) -> bytes:
    return _encode(_text_image(text, size, font_size), "JPEG", quality=95)


def webp_with_text(text: str = "Hola mundo", size=(800, 200), font_size: int = 36) -> bytes:
    return _encode(_text_image(text, size, font_size), "WEBP", quality=95)


def blank_png(size=(400, 300)) -> bytes:
    return _encode(Image.new("RGB", size, (90, 140, 200)), "PNG")


def png_rgba_transparent(size=(1200, 300)) -> bytes:
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((10, 10, 100, 100), fill=(0, 0, 0, 255))
    return _encode(image, "PNG")


def jpeg_with_exif_rotation(size=(1200, 400)) -> bytes:
    """JPEG de `size` con orientación EXIF 6 (se muestra rotado 90° en sentido horario)."""
    image = _text_image("Rotada", size, 36)
    exif = Image.Exif()
    exif[0x0112] = 6
    return _encode(image, "JPEG", exif=exif)


def gif_image() -> bytes:
    return _encode(Image.new("RGB", (50, 50), "white"), "GIF")


def huge_pixels_png(width: int = 6000, height: int = 5000) -> bytes:
    """30 MP de color sólido: pesa poco comprimido pero supera el límite de píxeles."""
    return _encode(Image.new("L", (width, height), 255), "PNG")


def fake_png_bytes() -> bytes:
    return b"esto no es una imagen, es texto plano con extension .png\n" * 4


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def image_payload(
    data: bytes | None = None, filename: str = "captura.png", media_type: str = "image/png"
) -> dict:
    return {
        "filename": filename,
        "media_type": media_type,
        "data": b64(data if data is not None else png_with_text()),
    }
