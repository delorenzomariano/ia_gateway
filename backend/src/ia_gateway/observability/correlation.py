"""Identificador de correlación por solicitud (header X-Correlation-ID)."""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

HEADER = "X-Correlation-ID"
_VALID = re.compile(r"^[A-Za-z0-9-]{1,64}$")

correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")


def get_correlation_id() -> str:
    return correlation_id.get()


class CorrelationIdMiddleware:
    """Reutiliza un X-Correlation-ID válido o genera uno, y lo agrega a toda respuesta.

    Implementado como middleware ASGI puro para no interferir con respuestas en streaming.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = None
        for name, value in scope["headers"]:
            if name.decode("latin-1").lower() == HEADER.lower():
                incoming = value.decode("latin-1")
                break
        cid = incoming if incoming and _VALID.match(incoming) else str(uuid.uuid4())
        token = correlation_id.set(cid)

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers[HEADER] = cid
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            correlation_id.reset(token)
