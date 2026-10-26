"""Errores de la API con formato uniforme {"error": {code, message, correlation_id}}."""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ia_gateway.observability.correlation import get_correlation_id

logger = logging.getLogger("ia_gateway.api")


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOTHING_TO_RETRY = "NOTHING_TO_RETRY"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    ACCESS_DENIED = "ACCESS_DENIED"
    CONVERSATION_NOT_FOUND = "CONVERSATION_NOT_FOUND"
    GENERATION_IN_PROGRESS = "GENERATION_IN_PROGRESS"
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
    LLM_TIMEOUT = "LLM_TIMEOUT"
    LLM_INVALID_RESPONSE = "LLM_INVALID_RESPONSE"
    IMAGE_INVALID = "IMAGE_INVALID"
    IMAGE_TOO_LARGE = "IMAGE_TOO_LARGE"
    IMAGE_NO_TEXT = "IMAGE_NO_TEXT"
    OCR_UNAVAILABLE = "OCR_UNAVAILABLE"
    OCR_TIMEOUT = "OCR_TIMEOUT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


STATUS: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.NOTHING_TO_RETRY: 422,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.METHOD_NOT_ALLOWED: 405,
    ErrorCode.ACCESS_DENIED: 403,
    ErrorCode.CONVERSATION_NOT_FOUND: 404,
    ErrorCode.GENERATION_IN_PROGRESS: 409,
    ErrorCode.LLM_UNAVAILABLE: 503,
    ErrorCode.LLM_TIMEOUT: 504,
    ErrorCode.LLM_INVALID_RESPONSE: 502,
    ErrorCode.IMAGE_INVALID: 422,
    ErrorCode.IMAGE_TOO_LARGE: 413,
    ErrorCode.IMAGE_NO_TEXT: 422,
    ErrorCode.OCR_UNAVAILABLE: 503,
    ErrorCode.OCR_TIMEOUT: 504,
    ErrorCode.INTERNAL_ERROR: 500,
}

MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.VALIDATION_ERROR: "El mensaje no es válido. Revisá el contenido e intentá de nuevo.",
    ErrorCode.NOTHING_TO_RETRY: "No hay ninguna respuesta para reintentar.",
    ErrorCode.NOT_FOUND: "El recurso solicitado no existe.",
    ErrorCode.METHOD_NOT_ALLOWED: "Operación no permitida sobre este recurso.",
    ErrorCode.ACCESS_DENIED: "No tenés acceso a este servicio desde tu ubicación.",
    ErrorCode.CONVERSATION_NOT_FOUND: "La conversación no existe o venció. Empezá una nueva.",
    ErrorCode.GENERATION_IN_PROGRESS: (
        "Ya hay una respuesta en curso en esta conversación. Esperá a que termine."
    ),
    ErrorCode.LLM_UNAVAILABLE: (
        "El asistente no está disponible en este momento. Reintentá en unos segundos."
    ),
    ErrorCode.LLM_TIMEOUT: (
        "El asistente está tardando demasiado en responder. Reintentá en unos segundos."
    ),
    ErrorCode.LLM_INVALID_RESPONSE: "El asistente devolvió una respuesta inválida. Reintentá.",
    ErrorCode.IMAGE_INVALID: "La imagen no es válida. Formatos admitidos: PNG, JPEG o WebP.",
    ErrorCode.IMAGE_TOO_LARGE: "La imagen supera el tamaño máximo permitido.",
    ErrorCode.IMAGE_NO_TEXT: "No se encontró texto legible en la imagen.",
    ErrorCode.OCR_UNAVAILABLE: "El análisis de imágenes no está disponible en este momento.",
    ErrorCode.OCR_TIMEOUT: "El análisis de la imagen tardó demasiado.",
    ErrorCode.INTERNAL_ERROR: "Ocurrió un error inesperado. Reintentá en unos segundos.",
}


class ApiError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str | None = None,
        details: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(code.value)
        self.code = code
        self.message = message or MESSAGES[code]
        self.details = details

    @property
    def status_code(self) -> int:
        return STATUS[self.code]


def error_body(
    code: ErrorCode, message: str | None = None, details: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": code.value,
        "message": message or MESSAGES[code],
        "correlation_id": get_correlation_id(),
    }
    if details is not None:
        error["details"] = details
    return {"error": error}


def error_response(
    code: ErrorCode, message: str | None = None, details: list[dict[str, str]] | None = None
) -> JSONResponse:
    return JSONResponse(status_code=STATUS[code], content=error_body(code, message, details))


async def _api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return error_response(exc.code, exc.message, exc.details)


async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    details = []
    for err in exc.errors():
        loc = [str(part) for part in err.get("loc", ()) if part not in ("body", "query", "path")]
        details.append({"field": ".".join(loc) or "body", "issue": err.get("msg", "inválido")})
    return error_response(ErrorCode.VALIDATION_ERROR, details=details)


async def _http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    if exc.status_code == 404:
        return error_response(ErrorCode.NOT_FOUND)
    if exc.status_code == 405:
        return error_response(ErrorCode.METHOD_NOT_ALLOWED)
    if exc.status_code == 413:
        # Cuerpo cortado por BodySizeLimitMiddleware mientras FastAPI lo leía.
        return error_response(ErrorCode.IMAGE_TOO_LARGE)
    logger.warning("http_exception", extra={"status": exc.status_code})
    code = ErrorCode.VALIDATION_ERROR if 400 <= exc.status_code < 500 else ErrorCode.INTERNAL_ERROR
    return error_response(code)


class UnhandledErrorMiddleware:
    """Convierte excepciones no manejadas en INTERNAL_ERROR con el formato uniforme.

    Va dentro del middleware de correlación (el handler `Exception` de Starlette corre fuera de
    todos los middlewares y perdería el correlation_id).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception:
            logger.exception("unhandled_error")
            if started:
                raise
            await error_response(ErrorCode.INTERNAL_ERROR)(scope, receive, send)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)  # type: ignore[arg-type]
