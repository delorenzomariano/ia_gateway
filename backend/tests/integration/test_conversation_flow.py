"""Flujo completo de US1 con el modelo simulado."""

import asyncio
from datetime import UTC, datetime, timedelta

import httpx

from ia_gateway.main import create_app
from ia_gateway.storage.sqlite import SqliteConversationRepository

from ..fakes import FakeLLMClient, Sleep, text_reply

JSON = {"Accept": "application/json"}


async def send(client, conv_id, content):
    return await client.post(
        f"/api/v1/conversations/{conv_id}/messages", json={"content": content}, headers=JSON
    )


async def test_multi_turn_context_and_history(client, fake_llm, settings):
    fake_llm.queue(text_reply("París."), text_reply("Unos 2,1 millones."))
    conv = (await client.post("/api/v1/conversations")).json()

    assert (await send(client, conv["id"], "¿Capital de Francia?")).status_code == 200
    assert (await send(client, conv["id"], "¿Y cuántos habitantes tiene?")).status_code == 200

    second_call = fake_llm.calls[1].messages
    assert second_call[0].role == "system"
    assert second_call[0].content == settings.system_prompt
    assert [(m.role, m.content) for m in second_call[1:]] == [
        ("user", "¿Capital de Francia?"),
        ("assistant", "París."),
        ("user", "¿Y cuántos habitantes tiene?"),
    ]
    assert fake_llm.calls[1].tools is None

    history = (await client.get(f"/api/v1/conversations/{conv['id']}")).json()["messages"]
    assert [(m["role"], m["content"]) for m in history] == [
        ("user", "¿Capital de Francia?"),
        ("assistant", "París."),
        ("user", "¿Y cuántos habitantes tiene?"),
        ("assistant", "Unos 2,1 millones."),
    ]


async def test_conversation_survives_app_restart(settings, tmp_path):
    async def run(app, fn):
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
                return await fn(c)

    async def first(c):
        conv = (await c.post("/api/v1/conversations")).json()
        await send(c, conv["id"], "recordame")
        return conv["id"]

    conv_id = await run(create_app(settings, llm_client=FakeLLMClient()), first)

    async def second(c):
        return (await c.get(f"/api/v1/conversations/{conv_id}")).json()

    body = await run(create_app(settings, llm_client=FakeLLMClient()), second)
    assert [m["content"] for m in body["messages"]][0] == "recordame"


async def test_expired_conversation_returns_404(settings):
    now = [datetime(2026, 10, 24, tzinfo=UTC)]
    repo = SqliteConversationRepository(
        settings.database_path, retention=settings.retention, clock=lambda: now[0]
    )
    app = create_app(settings, llm_client=FakeLLMClient(), repository=repo)
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            conv = (await c.post("/api/v1/conversations")).json()
            now[0] += timedelta(hours=24, seconds=1)
            response = await c.get(f"/api/v1/conversations/{conv['id']}")
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"
            assert (await send(c, conv["id"], "hola")).status_code == 404


async def test_concurrent_send_returns_409(client, fake_llm):
    fake_llm.queue([Sleep(0.3), *text_reply("lento")])
    conv = (await client.post("/api/v1/conversations")).json()

    first = asyncio.create_task(send(client, conv["id"], "uno"))
    await asyncio.sleep(0.05)
    busy = await client.get(f"/api/v1/conversations/{conv['id']}")
    assert busy.json()["generation_in_progress"] is True

    second = await send(client, conv["id"], "dos")
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "GENERATION_IN_PROGRESS"
    delete = await client.delete(f"/api/v1/conversations/{conv['id']}")
    assert delete.status_code == 409

    assert (await first).status_code == 200
    assert (await send(client, conv["id"], "tres")).status_code == 200
