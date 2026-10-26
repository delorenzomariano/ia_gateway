"""Utilidades de prueba para SSE: parseo de eventos y un cliente ASGI que puede desconectarse.

httpx.ASGITransport junta toda la respuesta antes de devolverla, así que para probar la
cancelación a mitad del stream se maneja el protocolo ASGI directamente.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        if not block.strip():
            continue
        name, data = "message", []
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data.append(line[len("data:") :].strip())
        events.append((name, json.loads("\n".join(data)) if data else {}))
    return events


@dataclass
class StreamResult:
    status: int | None = None
    headers: dict[str, str] = field(default_factory=dict)
    body: str = ""

    @property
    def events(self) -> list[tuple[str, dict]]:
        return parse_sse(self.body)


async def asgi_stream(
    app,
    path: str,
    body: dict,
    *,
    disconnect_after_events: int | None = None,
    timeout: float = 5,
) -> StreamResult:
    """POST con `Accept: text/event-stream`; se desconecta tras N eventos completos."""
    result = StreamResult()
    disconnected = asyncio.Event()
    payload = json.dumps(body).encode()
    sent_body = False

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"127.0.0.1"),
            (b"accept", b"text/event-stream"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode()),
        ],
        "client": ("127.0.0.1", 5000),
        "server": ("127.0.0.1", 80),
    }

    async def receive():
        nonlocal sent_body
        if not sent_body:
            sent_body = True
            return {"type": "http.request", "body": payload, "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            result.status = message["status"]
            result.headers = {k.decode().lower(): v.decode() for k, v in message["headers"]}
        elif message["type"] == "http.response.body":
            if disconnected.is_set():
                return
            result.body += message.get("body", b"").decode()
            if (
                disconnect_after_events is not None
                and result.body.count("\n\n") >= disconnect_after_events
            ):
                disconnected.set()

    await asyncio.wait_for(app(scope, receive, send), timeout)
    return result
