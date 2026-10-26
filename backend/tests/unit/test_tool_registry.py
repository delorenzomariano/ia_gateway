import asyncio

import pytest
from pydantic import BaseModel

from ia_gateway.config import Settings
from ia_gateway.tools.registry import Tool, ToolRegistry, build_registry


class EchoIn(BaseModel):
    text: str


class EchoOut(BaseModel):
    echoed: str


async def echo(args: EchoIn) -> EchoOut:
    return EchoOut(echoed=args.text)


def echo_tool(**overrides) -> Tool:
    params = dict(
        name="echo",
        description="Devuelve el texto recibido.",
        input_model=EchoIn,
        output_model=EchoOut,
        handler=echo,
    )
    params.update(overrides)
    return Tool(**params)


@pytest.mark.parametrize("name", ["Echo", "1echo", "eco-tool", "", "a" * 65])
def test_invalid_names_are_rejected(name):
    with pytest.raises(ValueError):
        echo_tool(name=name)


@pytest.mark.parametrize("description", ["", "x" * 1025])
def test_invalid_descriptions_are_rejected(description):
    with pytest.raises(ValueError):
        echo_tool(description=description)


def test_names_must_be_unique():
    registry = ToolRegistry()
    registry.register(echo_tool())
    with pytest.raises(ValueError):
        registry.register(echo_tool())


def test_tool_specs_use_json_schema_of_input():
    registry = ToolRegistry()
    registry.register(echo_tool())
    [spec] = registry.to_tool_specs()
    assert spec.name == "echo"
    assert spec.description == "Devuelve el texto recibido."
    assert spec.parameters["type"] == "object"
    assert spec.parameters["properties"]["text"]["type"] == "string"
    assert spec.parameters["required"] == ["text"]


async def test_execute_ok():
    registry = ToolRegistry()
    registry.register(echo_tool())
    result = await registry.execute("echo", {"text": "hola"})
    assert result.status == "ok"
    assert result.output == {"echoed": "hola"}
    assert result.duration_ms >= 0


async def test_unknown_tool_is_rejected():
    result = await ToolRegistry().execute("borrar_todo", {})
    assert result.status == "rejected"
    assert "no registrada" in result.error


async def test_invalid_arguments_are_rejected():
    registry = ToolRegistry()
    registry.register(echo_tool())
    result = await registry.execute("echo", {"texto": 1})
    assert result.status == "rejected"
    assert result.output is None


async def test_invalid_output_is_error():
    async def bad(_: EchoIn) -> dict:
        return {"otro": 1}

    registry = ToolRegistry()
    registry.register(echo_tool(handler=bad))
    result = await registry.execute("echo", {"text": "x"})
    assert result.status == "error"


async def test_timeout_is_error():
    async def slow(args: EchoIn) -> EchoOut:
        await asyncio.sleep(1)
        return EchoOut(echoed=args.text)

    registry = ToolRegistry()
    registry.register(echo_tool(handler=slow, timeout_s=0.05))
    result = await registry.execute("echo", {"text": "x"})
    assert result.status == "error"
    assert "tiempo" in result.error


async def test_handler_exception_is_error_without_leaking_details():
    async def boom(_: EchoIn) -> EchoOut:
        raise RuntimeError("secreto interno")

    registry = ToolRegistry()
    registry.register(echo_tool(handler=boom))
    result = await registry.execute("echo", {"text": "x"})
    assert result.status == "error"
    assert "secreto" not in result.for_model()


def test_default_timeout_is_10_seconds():
    assert echo_tool().timeout_s == 10


def test_build_registry_only_registers_enabled_tools():
    assert len(build_registry(Settings(_env_file=None))) == 0
    registry = build_registry(Settings(_env_file=None, tools_enabled="current_time"))
    assert [s.name for s in registry.to_tool_specs()] == ["current_time"]


def test_build_registry_rejects_unknown_tools():
    with pytest.raises(ValueError):
        build_registry(Settings(_env_file=None, tools_enabled="no_existe"))


async def test_current_time_tool():
    registry = build_registry(Settings(_env_file=None, tools_enabled=["current_time"]))
    result = await registry.execute("current_time", {})
    assert result.status == "ok"
    assert set(result.output) == {"iso", "timezone"}
