"""Herramienta de prueba: fecha y hora actuales del servidor."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from ia_gateway.tools.registry import Tool


class CurrentTimeInput(BaseModel):
    pass


class CurrentTimeOutput(BaseModel):
    iso: str
    timezone: str


async def current_time(_: CurrentTimeInput) -> CurrentTimeOutput:
    now = datetime.now().astimezone()
    return CurrentTimeOutput(iso=now.isoformat(timespec="seconds"), timezone=str(now.tzinfo))


def build() -> Tool:
    return Tool(
        name="current_time",
        description=(
            "Devuelve la fecha y hora actuales del servidor (ISO 8601) y su zona horaria. "
            "Usala cuando te pregunten la hora o la fecha de hoy."
        ),
        input_model=CurrentTimeInput,
        output_model=CurrentTimeOutput,
        handler=current_time,
    )
