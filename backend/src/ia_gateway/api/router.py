"""Router de la API v1.

Punto único para agregar autenticación (excepción documentada en plan.md): cuando se exponga el
servicio fuera de la red local, agregar `dependencies=[Depends(require_auth)]` a este router.
"""

from fastapi import APIRouter

from ia_gateway.api.errors import STATUS, ErrorCode
from ia_gateway.api.schemas import ErrorResponse


def error_responses(*codes: ErrorCode) -> dict[int | str, dict]:
    """Declara en el OpenAPI las respuestas de error de una operación."""
    responses: dict[int | str, dict] = {}
    for code in codes:
        entry = responses.setdefault(STATUS[code], {"model": ErrorResponse, "description": ""})
        entry["description"] = " | ".join(filter(None, [entry["description"], code.value]))
    return responses


def build_api_router() -> APIRouter:
    # Importación diferida: los módulos de rutas importan `error_responses` de este archivo.
    from ia_gateway.api import conversations, health

    router = APIRouter(prefix="/api/v1")
    router.include_router(health.router)
    router.include_router(conversations.router)
    return router
