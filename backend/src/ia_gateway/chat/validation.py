"""Saneamiento de la salida del modelo: se trata como contenido no confiable (FR-015)."""

from __future__ import annotations

import re

from ia_gateway.llm.base import LLMInvalidResponseError

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def remove_control_chars(text: str) -> str:
    """Elimina caracteres de control salvo salto de línea y tabulación."""
    return _CONTROL.sub("", text)


def sanitize_llm_text(text: str, had_tool_calls: bool = False) -> str:
    cleaned = remove_control_chars(text).strip()
    if not cleaned and not had_tool_calls:
        raise LLMInvalidResponseError("el modelo devolvió una respuesta vacía")
    return cleaned


class StreamSanitizer:
    """Sanea fragmentos a medida que llegan.

    Descarta el espacio inicial y retiene el espacio final de cada fragmento hasta que llega
    texto visible, de modo que la concatenación de lo emitido es exactamente el texto saneado.
    """

    def __init__(self) -> None:
        self._started = False
        self._pending = ""
        self._parts: list[str] = []

    def feed(self, raw: str) -> str:
        text = remove_control_chars(raw)
        if not self._started:
            text = text.lstrip()
            if not text:
                return ""
            self._started = True
        text = self._pending + text
        visible = text.rstrip()
        self._pending = text[len(visible) :]
        if visible:
            self._parts.append(visible)
        return visible

    @property
    def text(self) -> str:
        return "".join(self._parts)
