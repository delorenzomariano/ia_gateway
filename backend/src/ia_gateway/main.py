"""Punto de entrada: `uvicorn ia_gateway.main:app`."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from ia_gateway.api.access import NetworkAccessMiddleware, parse_networks
from ia_gateway.api.errors import UnhandledErrorMiddleware, install_error_handlers
from ia_gateway.api.limits import BodySizeLimitMiddleware
from ia_gateway.api.router import build_api_router
from ia_gateway.chat.images import ImageReader
from ia_gateway.chat.locks import GenerationLocks
from ia_gateway.chat.orchestrator import ChatOrchestrator
from ia_gateway.config import Settings
from ia_gateway.llm.base import LLMClient
from ia_gateway.main_deps import Services
from ia_gateway.observability.correlation import HEADER, CorrelationIdMiddleware
from ia_gateway.observability.logging import RequestLogMiddleware, configure_logging
from ia_gateway.ocr.base import OcrEngine
from ia_gateway.storage.repository import ConversationRepository
from ia_gateway.storage.sqlite import SqliteConversationRepository
from ia_gateway.tools.registry import ToolRegistry, build_registry

logger = logging.getLogger("ia_gateway")

FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"


def _default_llm(settings: Settings) -> LLMClient:
    from ia_gateway.llm.ollama import OllamaClient

    return OllamaClient(settings)


def _default_ocr(settings: Settings) -> OcrEngine:
    from ia_gateway.ocr.tesseract import TesseractOcrEngine

    return TesseractOcrEngine(settings)


def create_app(
    settings: Settings | None = None,
    llm_client: LLMClient | None = None,
    repository: ConversationRepository | None = None,
    tool_registry: ToolRegistry | None = None,
    ocr_engine: OcrEngine | None = None,
) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level, settings.diagnostic_mode)

    repository = repository or SqliteConversationRepository(
        settings.database_path, retention=settings.retention
    )
    llm = llm_client or _default_llm(settings)
    locks = GenerationLocks()
    tools = tool_registry if tool_registry is not None else build_registry(settings)
    ocr = ocr_engine or _default_ocr(settings)
    services = Services(
        settings=settings,
        repository=repository,
        llm=llm,
        locks=locks,
        orchestrator=ChatOrchestrator(settings, repository, llm, locks, tools),
        ocr=ocr,
        image_reader=ImageReader(settings, ocr),
    )

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await services.repository.initialize()
        removed = await services.repository.delete_expired()
        logger.info(
            "startup",
            extra={
                "expired_removed": removed,
                "model": services.llm.model,
                "tools": [s.name for s in tools.to_tool_specs()],
            },
        )
        cleanup = asyncio.create_task(_cleanup_loop(services))
        try:
            yield
        finally:
            cleanup.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cleanup
            await services.llm.aclose()

    # El primer middleware de la lista es el más externo. El límite del cuerpo va al final:
    # sus 413 llevan correlation_id y cabeceras CORS, y no se lee el cuerpo de clientes no
    # permitidos.
    middleware = [
        Middleware(CorrelationIdMiddleware),
        Middleware(RequestLogMiddleware),
        Middleware(UnhandledErrorMiddleware),
        Middleware(
            CORSMiddleware,
            allow_origins=settings.allowed_origins,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "Accept", HEADER],
            expose_headers=[HEADER],
        ),
        Middleware(NetworkAccessMiddleware, networks=parse_networks(settings.allowed_networks)),
        Middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_body_bytes),
    ]

    app = FastAPI(
        title="IA Gateway API",
        version="1.1.0",
        lifespan=lifespan,
        middleware=middleware,
    )
    app.state.services = services
    install_error_handlers(app)
    app.include_router(build_api_router())

    if settings.serve_frontend and FRONTEND_DIR.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

    return app


async def _cleanup_loop(services: Services) -> None:
    interval = services.settings.cleanup_interval_minutes * 60
    while True:
        await asyncio.sleep(interval)
        try:
            removed = await services.repository.delete_expired()
            if removed:
                logger.info("expired_conversations_removed", extra={"count": removed})
        except Exception:
            logger.exception("cleanup_failed")


def __getattr__(name: str) -> FastAPI:
    # `app` se crea al primer acceso para que importar el módulo (p. ej. en pruebas) no lea .env.
    if name == "app":
        globals()["app"] = application = create_app()
        return application
    raise AttributeError(name)
