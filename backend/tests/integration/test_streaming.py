"""Cancelación y mantenimiento de conexión en el modo SSE (US2)."""

import asyncio

import pytest

from ia_gateway.main import create_app

from ..fakes import FakeLLMClient, Sleep, text_reply
from ..sse_utils import asgi_stream


@pytest.fixture
def stream_settings(settings):
    return settings.model_copy(update={"sse_ping_interval_s": 0.05})


async def _run(app, fn):
    async with app.router.lifespan_context(app):
        return await fn()


async def test_cancel_mid_stream_saves_incomplete_message(stream_settings):
    llm = FakeLLMClient()
    llm.queue([*text_reply("Primera parte. ")[:-1], Sleep(2), *text_reply("Nunca llega.")])
    app = create_app(stream_settings, llm_client=llm)
    services = app.state.services

    async def scenario():
        conv = await services.repository.create_conversation()
        result = await asgi_stream(
            app,
            f"/api/v1/conversations/{conv.id}/messages",
            {"content": "Contame algo largo"},
            disconnect_after_events=2,  # message.start + primer delta
        )
        await asyncio.sleep(0.1)
        return conv, result

    conv, result = await _run(app, scenario)
    assert [name for name, _ in result.events][:2] == ["message.start", "delta"]
    assert llm.cancelled == 1
    assert not services.locks.is_busy(conv.id)

    messages = await services.repository.list_messages(conv.id)
    assert [(m.role, m.status, m.content) for m in messages] == [
        ("user", "complete", "Contame algo largo"),
        ("assistant", "incomplete", "Primera parte."),
    ]


async def test_cancel_before_any_text_saves_nothing(stream_settings):
    llm = FakeLLMClient()
    llm.queue([Sleep(2), *text_reply("tarde")])
    app = create_app(stream_settings, llm_client=llm)
    services = app.state.services

    async def scenario():
        conv = await services.repository.create_conversation()
        await asgi_stream(
            app,
            f"/api/v1/conversations/{conv.id}/messages",
            {"content": "hola"},
            disconnect_after_events=1,  # solo message.start
        )
        await asyncio.sleep(0.1)
        return conv

    conv = await _run(app, scenario)
    messages = await services.repository.list_messages(conv.id)
    assert [m.role for m in messages] == ["user"]
    assert not services.locks.is_busy(conv.id)


async def test_ping_is_sent_while_waiting(stream_settings):
    llm = FakeLLMClient()
    llm.queue([Sleep(0.2), *text_reply("listo")])
    app = create_app(stream_settings, llm_client=llm)
    services = app.state.services

    async def scenario():
        conv = await services.repository.create_conversation()
        return await asgi_stream(
            app, f"/api/v1/conversations/{conv.id}/messages", {"content": "hola"}
        )

    result = await _run(app, scenario)
    names = [name for name, _ in result.events]
    assert "ping" in names
    assert names[0] == "message.start" and names[-1] == "message.end"
    assert names.index("ping") < names.index("delta")
