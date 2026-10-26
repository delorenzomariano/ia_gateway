"""Serialización de eventos SSE y mantenimiento de conexión (contracts/sse-events.md)."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any

import anyio

PING = object()


def format_event(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


async def with_pings[T](source: AsyncIterator[T], interval: float) -> AsyncIterator[T | object]:
    """Reenvía los elementos de `source` y emite PING tras `interval` segundos sin actividad.

    Si el consumidor se cancela (p. ej. el cliente se desconectó), se cancela `source` y se
    espera a que termine su limpieza (guardar la respuesta incompleta) antes de salir.
    """
    iterator = aiter(source)
    pending: asyncio.Task | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(anext(iterator))
            done, _ = await asyncio.wait({pending}, timeout=interval)
            if not done:
                yield PING
                continue
            task, pending = pending, None
            try:
                yield task.result()
            except StopAsyncIteration:
                return
    finally:
        with anyio.CancelScope(shield=True):
            if pending is not None and not pending.done():
                pending.cancel()
                with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration, Exception):
                    await pending
            aclose = getattr(iterator, "aclose", None)
            if aclose is not None:
                with contextlib.suppress(Exception):
                    await aclose()
