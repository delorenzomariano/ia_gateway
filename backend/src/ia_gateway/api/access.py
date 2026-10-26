"""Restricción de acceso por red de cliente (FR-011).

Excepción documentada en plan.md (Complexity Tracking): en v1 no hay autenticación de usuarios;
el acceso a `/api/` se limita a las redes configuradas en IA_GATEWAY_ALLOWED_NETWORKS. Se
aplica como middleware para cubrir también rutas inexistentes (no revela qué rutas existen).
"""

from __future__ import annotations

import ipaddress
import logging

from starlette.types import ASGIApp, Receive, Scope, Send

from ia_gateway.api.errors import ErrorCode, error_response

logger = logging.getLogger("ia_gateway.access")

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


def parse_networks(values: list[str]) -> list[IPNetwork]:
    return [ipaddress.ip_network(value, strict=False) for value in values]


def is_allowed(host: str | None, networks: list[IPNetwork]) -> bool:
    if not host:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return any(address in network for network in networks)


class NetworkAccessMiddleware:
    def __init__(self, app: ASGIApp, networks: list[IPNetwork], prefix: str = "/api/") -> None:
        self.app = app
        self.networks = networks
        self.prefix = prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"].startswith(self.prefix):
            client = scope.get("client")
            host = client[0] if client else None
            if not is_allowed(host, self.networks):
                logger.warning("access_denied", extra={"client_ip": host, "path": scope["path"]})
                await error_response(ErrorCode.ACCESS_DENIED)(scope, receive, send)
                return
        await self.app(scope, receive, send)
