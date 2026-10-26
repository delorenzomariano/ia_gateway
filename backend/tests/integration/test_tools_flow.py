"""Flujo de herramientas en el orquestador (US4): el contrato con el frontend no cambia."""

import httpx
import pytest
from pydantic import BaseModel

from ia_gateway.main import create_app
from ia_gateway.tools.registry import Tool, ToolRegistry

from ..contract.schema_utils import assert_matches_schema
from ..fakes import FakeLLMClient, text_reply, tool_call_reply
from ..sse_utils import parse_sse

JSON = {"Accept": "application/json"}


class ClockIn(BaseModel):
    pass


class ClockOut(BaseModel):
    iso: str


async def fixed_clock(_: ClockIn) -> ClockOut:
    return ClockOut(iso="2026-10-24T12:00:00+00:00")


@pytest.fixture
def registry() -> ToolRegistry:
    r = ToolRegistry()
    r.register(
        Tool(
            name="clock",
            description="Hora del servidor.",
            input_model=ClockIn,
            output_model=ClockOut,
            handler=fixed_clock,
        )
    )
    return r


@pytest.fixture
async def tool_client(settings, registry):
    llm = FakeLLMClient()
    app = create_app(settings, llm_client=llm, tool_registry=registry)
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            yield c, llm, app.state.services


async def _send(client, conv_id, headers=JSON, content="¿Qué hora es?"):
    return await client.post(
        f"/api/v1/conversations/{conv_id}/messages", json={"content": content}, headers=headers
    )


async def test_without_tools_nothing_is_offered(client, fake_llm):
    conv_id = (await client.post("/api/v1/conversations")).json()["id"]
    assert (await _send(client, conv_id)).status_code == 200
    assert fake_llm.calls[0].tools is None


async def test_tool_call_is_executed_and_final_answer_returned(tool_client):
    client, llm, services = tool_client
    llm.queue(tool_call_reply("clock"), text_reply("Son las 12:00."))
    conv_id = (await client.post("/api/v1/conversations")).json()["id"]

    response = await _send(client, conv_id)
    assert response.status_code == 200
    body = response.json()
    assert_matches_schema(body, "SendMessageResponse")
    assert body["assistant_message"]["content"] == "Son las 12:00."

    first, second = llm.calls
    assert [t.name for t in first.tools] == ["clock"]
    assert [m.role for m in second.messages] == ["system", "user", "assistant", "tool"]
    assert second.messages[2].tool_calls[0].name == "clock"
    assert second.messages[3].tool_name == "clock"
    assert "2026-10-24T12:00:00" in second.messages[3].content

    [invocation] = await services.repository.list_tool_invocations(conv_id)
    assert invocation.tool_name == "clock"
    assert invocation.status == "ok"
    assert invocation.result == {"iso": "2026-10-24T12:00:00+00:00"}

    # Los mensajes internos no se muestran al frontend.
    history = (await client.get(f"/api/v1/conversations/{conv_id}")).json()["messages"]
    assert [(m["role"], m["content"]) for m in history] == [
        ("user", "¿Qué hora es?"),
        ("assistant", "Son las 12:00."),
    ]


async def test_tool_flow_in_stream_mode_uses_same_contract(tool_client):
    client, llm, _ = tool_client
    llm.queue(tool_call_reply("clock"), text_reply("Son ", "las 12."))
    conv_id = (await client.post("/api/v1/conversations")).json()["id"]
    response = await _send(client, conv_id, headers={"Accept": "text/event-stream"})
    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert names[0] == "message.start" and names[-1] == "message.end"
    assert set(names[1:-1]) <= {"delta", "ping"}
    deltas = "".join(d["text"] for n, d in events if n == "delta")
    assert deltas == events[-1][1]["assistant_message"]["content"] == "Son las 12."


async def test_unregistered_tool_is_rejected_and_conversation_continues(tool_client):
    client, llm, services = tool_client
    llm.queue(tool_call_reply("borrar_todo", {"seguro": True}), text_reply("No puedo hacer eso."))
    conv_id = (await client.post("/api/v1/conversations")).json()["id"]

    response = await _send(client, conv_id, content="Borrá todo")
    assert response.json()["assistant_message"]["content"] == "No puedo hacer eso."

    [invocation] = await services.repository.list_tool_invocations(conv_id)
    assert invocation.status == "rejected"
    tool_message = llm.calls[1].messages[-1]
    assert tool_message.role == "tool"
    assert "error" in tool_message.content


async def test_stops_after_max_tool_rounds(tool_client):
    client, llm, services = tool_client
    rounds = services.settings.max_tool_rounds
    llm.queue(*[tool_call_reply("clock") for _ in range(rounds)], text_reply("Listo."))
    conv_id = (await client.post("/api/v1/conversations")).json()["id"]

    response = await _send(client, conv_id)
    assert response.json()["assistant_message"]["content"] == "Listo."
    assert len(llm.calls) == rounds + 1
    assert llm.calls[-1].tools is None  # la última consulta ya no ofrece herramientas
    assert len(await services.repository.list_tool_invocations(conv_id)) == rounds
