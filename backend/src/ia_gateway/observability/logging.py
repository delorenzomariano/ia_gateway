"""Logging estructurado en JSON con correlation_id; texto de mensajes solo en modo diagnóstico."""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import UTC, datetime
from typing import Any

from ia_gateway.observability.correlation import get_correlation_id

_STANDARD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
}

_diagnostic_mode = False


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": get_correlation_id(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO", diagnostic_mode: bool = False) -> None:
    global _diagnostic_mode
    _diagnostic_mode = diagnostic_mode

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("ia_gateway")
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    root.propagate = False

    if diagnostic_mode:
        root.warning(
            "MODO DIAGNÓSTICO ACTIVO: los logs incluyen el texto de los mensajes. "
            "No usar con datos sensibles.",
            extra={"event": "diagnostic_mode_enabled"},
        )


class RequestLogMiddleware:
    """Registra método, ruta, estado y duración de cada solicitud HTTP."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.logger = logging.getLogger("ia_gateway.request")

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        status = 500

        async def capture(message: Any) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            self.logger.info(
                "request",
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": status,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                },
            )


def log_content(field: str, text: str) -> dict[str, str]:
    """Campos extra con el texto de un mensaje, solo si el modo diagnóstico está activo."""
    return {field: text} if _diagnostic_mode else {}
