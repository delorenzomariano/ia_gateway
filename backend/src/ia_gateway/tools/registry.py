"""Registro de herramientas que el modelo puede solicitar (FR-017/018).

Solo se ejecutan herramientas registradas; argumentos y resultados se validan contra sus
esquemas. Las herramientas disponibles se habilitan con IA_GATEWAY_TOOLS_ENABLED.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from ia_gateway.config import Settings
from ia_gateway.llm.base import ToolSpec

logger = logging.getLogger("ia_gateway.tools")

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

Handler = Callable[[Any], Awaitable[BaseModel | dict[str, Any]]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: Handler
    timeout_s: float = 10

    def __post_init__(self) -> None:
        if not _NAME.match(self.name):
            raise ValueError(f"nombre de herramienta inválido: {self.name!r}")
        if not 1 <= len(self.description) <= 1024:
            raise ValueError("la descripción debe tener entre 1 y 1024 caracteres")
        if self.timeout_s <= 0:
            raise ValueError("timeout_s debe ser positivo")


@dataclass(frozen=True)
class ToolResult:
    status: Literal["ok", "error", "rejected"]
    duration_ms: int
    output: dict[str, Any] | None = None
    error: str | None = None

    def for_model(self) -> str:
        """Contenido del mensaje `tool` que se devuelve al modelo."""
        if self.status == "ok":
            return json.dumps(self.output, ensure_ascii=False)
        return json.dumps({"error": self.error}, ensure_ascii=False)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"herramienta duplicada: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def __len__(self) -> int:
        return len(self._tools)

    def to_tool_specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name=tool.name,
                description=tool.description,
                parameters=tool.input_model.model_json_schema(),
            )
            for tool in self._tools.values()
        ]

    async def execute(self, name: str, arguments: Any) -> ToolResult:
        started = time.perf_counter()

        def elapsed() -> int:
            return int((time.perf_counter() - started) * 1000)

        tool = self._tools.get(name)
        if tool is None:
            return ToolResult("rejected", elapsed(), error=f"herramienta no registrada: {name}")
        try:
            parsed = tool.input_model.model_validate(arguments or {})
        except ValidationError as exc:
            return ToolResult("rejected", elapsed(), error=f"argumentos inválidos: {exc.errors()}")

        try:
            raw = await asyncio.wait_for(tool.handler(parsed), timeout=tool.timeout_s)
        except TimeoutError:
            message = f"se superó el tiempo de {tool.timeout_s} s"
            return ToolResult("error", elapsed(), error=message)
        except Exception:
            logger.exception("tool_failed", extra={"tool": name})
            return ToolResult("error", elapsed(), error="la herramienta falló")

        try:
            data = raw.model_dump(mode="json") if isinstance(raw, BaseModel) else raw
            output = tool.output_model.model_validate(data).model_dump(mode="json")
        except ValidationError:
            message = "la herramienta devolvió un resultado inválido"
            return ToolResult("error", elapsed(), error=message)
        return ToolResult("ok", elapsed(), output=output)


def _available_tools() -> dict[str, Callable[[], Tool]]:
    from ia_gateway.tools import current_time

    return {"current_time": current_time.build}


def build_registry(settings: Settings) -> ToolRegistry:
    registry = ToolRegistry()
    available = _available_tools()
    for name in settings.tools_enabled:
        if name not in available:
            raise ValueError(
                f"IA_GATEWAY_TOOLS_ENABLED incluye una herramienta desconocida: {name}. "
                f"Disponibles: {', '.join(sorted(available))}"
            )
        registry.register(available[name]())
    return registry
