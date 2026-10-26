from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from ia_gateway.config import Settings
from ia_gateway.main import create_app

from .fakes import FakeLLMClient, FakeOcrEngine


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        database_path=str(tmp_path / "test.db"),
        serve_frontend=False,
        cleanup_interval_minutes=60,
    )


@pytest.fixture
def fake_llm() -> FakeLLMClient:
    return FakeLLMClient()


@pytest.fixture
def fake_ocr() -> FakeOcrEngine:
    return FakeOcrEngine()


@pytest.fixture
def app(settings, fake_llm, fake_ocr) -> FastAPI:
    return create_app(settings, llm_client=fake_llm, ocr_engine=fake_ocr)


@pytest.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 5000))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as c:
            c.app = app  # type: ignore[attr-defined]
            yield c


@pytest.fixture
def services_of():
    """Acceso a los servicios internos de la app detrás de un cliente de prueba."""
    return lambda client: client.app.state.services
