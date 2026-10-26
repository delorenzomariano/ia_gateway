"""Adaptador TesseractOcrEngine con pytesseract simulado (no requiere Tesseract instalado)."""

import pytesseract
import pytest
from PIL import Image

from ia_gateway.config import Settings
from ia_gateway.ocr import tesseract as module
from ia_gateway.ocr.base import OcrFailedError, OcrTimeoutError, OcrUnavailableError
from ia_gateway.ocr.tesseract import TesseractOcrEngine


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(_env_file=None, database_path=str(tmp_path / "x.db"))


def words(*items):
    """items: (block, par, line, text, conf)."""
    keys = ("block_num", "par_num", "line_num", "text", "conf")
    data = {key: [] for key in (*keys, "level", "word_num")}
    for item in items:
        for key, value in zip(keys, item, strict=True):
            data[key].append(value)
        data["level"].append(5)
        data["word_num"].append(1)
    return data


IMAGE = Image.new("L", (100, 50), 255)


def test_reconstructs_lines_and_paragraphs(monkeypatch, settings):
    calls = {}

    def fake_image_to_data(image, **kwargs):
        calls.update(kwargs)
        return words(
            (1, 1, 1, "", -1),
            (1, 1, 1, "Hola", 95),
            (1, 1, 1, "mundo", 90.5),
            (1, 1, 2, "segunda", "88"),
            (1, 1, 2, "línea", 80),
            (1, 2, 1, "Otro", 70),
            (2, 1, 1, "Bloque", 99),
            (2, 1, 1, "ruido", 12),
        )

    monkeypatch.setattr(module.pytesseract, "image_to_data", fake_image_to_data)
    result = TesseractOcrEngine(settings).recognize(IMAGE, timeout_s=7)

    assert result.text == "Hola mundo\nsegunda línea\n\nOtro\n\nBloque"
    assert result.word_count == 6
    assert result.dropped_words == 1
    assert result.duration_ms >= 0
    assert calls["lang"] == "spa+eng"
    assert calls["config"] == "--oem 1 --psm 3"
    assert calls["timeout"] == 7
    assert calls["output_type"] == pytesseract.Output.DICT


def test_min_confidence_is_configurable(monkeypatch, settings):
    monkeypatch.setattr(
        module.pytesseract, "image_to_data", lambda image, **kw: words((1, 1, 1, "dudoso", 40))
    )
    strict = TesseractOcrEngine(settings).recognize(IMAGE, timeout_s=1)
    lax = TesseractOcrEngine(settings.model_copy(update={"ocr_min_confidence": 30})).recognize(
        IMAGE, timeout_s=1
    )
    assert (strict.text, lax.text) == ("", "dudoso")


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (RuntimeError("Tesseract process timeout"), OcrTimeoutError),
        (pytesseract.TesseractNotFoundError(), OcrUnavailableError),
        (pytesseract.TesseractError(1, "Failed loading language 'spa'"), OcrUnavailableError),
        (pytesseract.TesseractError(1, "algo raro"), OcrFailedError),
        (RuntimeError("otra cosa"), OcrFailedError),
    ],
)
def test_maps_errors(monkeypatch, settings, error, expected):
    def boom(image, **kwargs):
        raise error

    monkeypatch.setattr(module.pytesseract, "image_to_data", boom)
    with pytest.raises(expected):
        TesseractOcrEngine(settings).recognize(IMAGE, timeout_s=1)


def test_custom_tesseract_cmd(monkeypatch, settings):
    monkeypatch.setattr(module.pytesseract.pytesseract, "tesseract_cmd", "tesseract")
    TesseractOcrEngine(settings.model_copy(update={"ocr_tesseract_cmd": r"C:\T\tesseract.exe"}))
    assert module.pytesseract.pytesseract.tesseract_cmd == r"C:\T\tesseract.exe"


async def test_health_ok_and_cached(monkeypatch, settings):
    calls = []
    monkeypatch.setattr(
        module.pytesseract,
        "get_languages",
        lambda config="": calls.append(1) or ["eng", "osd", "spa"],
    )
    engine = TesseractOcrEngine(settings)
    first = await engine.health()
    second = await engine.health()
    assert first.ok is True
    assert first.languages == ["spa", "eng"]
    assert second == first
    assert len(calls) == 1


async def test_health_cache_expires(monkeypatch, settings):
    now = [1000.0]
    calls = []
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(
        module.pytesseract, "get_languages", lambda config="": calls.append(1) or ["eng", "spa"]
    )
    engine = TesseractOcrEngine(settings)
    await engine.health()
    now[0] += 61
    await engine.health()
    assert len(calls) == 2


async def test_health_reports_missing_language(monkeypatch, settings):
    monkeypatch.setattr(module.pytesseract, "get_languages", lambda config="": ["eng", "osd"])
    health = await TesseractOcrEngine(settings).health()
    assert health.ok is False
    assert "spa" in health.detail
    assert health.languages == ["eng"]


async def test_health_reports_missing_tesseract(monkeypatch, settings):
    def missing(config=""):
        raise pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(module.pytesseract, "get_languages", missing)
    health = await TesseractOcrEngine(settings).health()
    assert health.ok is False
    assert "Tesseract" in health.detail
    assert health.languages == []
