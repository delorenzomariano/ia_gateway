"""Límite del tamaño del cuerpo de las solicitudes a /api/ (research.md R3).

FastAPI lee y decodifica el JSON completo antes de ejecutar el endpoint, así que el límite se
aplica acá, antes de que el cuerpo llegue a la aplicación.
"""

from __future__ import annotations

from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ia_gateway.api.errors import ErrorCode, error_response


class BodyTooLargeError(HTTPException):
    def __init__(self) -> None:
        super().__init__(status_code=413)


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return

        declared = _content_length(scope)
        if declared is not None and declared > self.max_bytes:
            await error_response(ErrorCode.IMAGE_TOO_LARGE)(scope, receive, send)
            return

        # Sin Content-Length (o si miente) se cuentan los bytes a medida que llegan.
        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise BodyTooLargeError()
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except BodyTooLargeError:
            if started:
                raise
            await error_response(ErrorCode.IMAGE_TOO_LARGE)(scope, receive, send)


def _content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", []):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None
