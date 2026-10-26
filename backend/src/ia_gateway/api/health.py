"""GET /api/v1/health: estado del backend, la base, el modelo y el OCR (FR-020, 002 FR-012)."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ia_gateway.api.schemas import (
    Health,
    HealthCheck,
    HealthChecks,
    LlmHealthCheck,
    OcrHealthCheck,
)
from ia_gateway.main_deps import Services, get_services

logger = logging.getLogger("ia_gateway.health")

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    operation_id="getHealth",
    response_model=Health,
    responses={503: {"model": Health, "description": "Alguna dependencia no está disponible"}},
)
async def get_health(services: Annotated[Services, Depends(get_services)]) -> JSONResponse:
    try:
        await services.repository.ping()
        database = HealthCheck(status="ok")
    except Exception as exc:  # cualquier falla de la base se informa, no se propaga
        logger.warning("health_database_failed", extra={"error": str(exc)})
        database = HealthCheck(status="error", detail="la base de datos no responde")

    llm_health = await services.llm.health()
    llm = LlmHealthCheck(
        status="ok" if llm_health.ok and llm_health.model_available else "error",
        detail=llm_health.detail,
        model=llm_health.model,
        model_available=llm_health.model_available,
    )

    ocr = await _ocr_check(services)

    # Con el OCR deshabilitado por configuración no se lo considera una dependencia.
    healthy = database.status == "ok" and llm.status == "ok" and ocr.status != "error"
    body = Health(
        status="ok" if healthy else "degraded",
        checks=HealthChecks(database=database, llm=llm, ocr=ocr),
    )
    return JSONResponse(
        status_code=200 if healthy else 503, content=body.model_dump(mode="json", exclude_none=True)
    )


async def _ocr_check(services: Services) -> OcrHealthCheck:
    if not services.settings.ocr_enabled:
        return OcrHealthCheck(status="disabled")
    try:
        health = await services.ocr.health()
    except Exception as exc:  # una falla del chequeo se informa, no se propaga
        logger.warning("health_ocr_failed", extra={"error": str(exc)})
        return OcrHealthCheck(status="error", detail="el reconocimiento de texto no responde")
    return OcrHealthCheck(
        status="ok" if health.ok else "error", detail=health.detail, languages=health.languages
    )
