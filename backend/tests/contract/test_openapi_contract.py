"""El OpenAPI generado por la app coincide con contracts/openapi.yaml (principio I)."""

import re

import pytest

from .schema_utils import load_openapi

# Cada historia agrega aquí las operaciones que implementa (T010, T020, T051, T071).
IMPLEMENTED_OPERATIONS: set[str] = {
    # US1
    "getHealth",
    "createConversation",
    "getConversation",
    "deleteConversation",
    "sendMessage",
    # US3
    "retryLastMessage",
}

_HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def _normalize(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


def _operations(spec: dict) -> dict[str, tuple[str, str, set[str]]]:
    ops = {}
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if method in _HTTP_METHODS:
                ops[op["operationId"]] = (_normalize(path), method, set(op["responses"]))
    return ops


@pytest.fixture
def generated(app) -> dict:
    return app.openapi()


def _generated_by_route(generated: dict) -> dict[tuple[str, str], set[str]]:
    out = {}
    for path, item in generated["paths"].items():
        for method, op in item.items():
            if method in _HTTP_METHODS:
                out[(_normalize(path), method)] = set(op.get("responses", {}))
    return out


def test_every_documented_operation_is_implemented():
    documented = set(_operations(load_openapi()))
    missing = documented - IMPLEMENTED_OPERATIONS
    assert not missing, f"Operaciones documentadas sin implementar: {missing}"


def test_implemented_operations_exist_in_contract():
    documented = _operations(load_openapi())
    missing = IMPLEMENTED_OPERATIONS - documented.keys()
    assert not missing, f"Operaciones no documentadas en openapi.yaml: {missing}"


@pytest.mark.parametrize("operation_id", sorted(IMPLEMENTED_OPERATIONS))
def test_operation_matches_contract(operation_id, generated):
    path, method, documented_codes = _operations(load_openapi())[operation_id]
    routes = _generated_by_route(generated)
    assert (path, method) in routes, f"{operation_id}: falta {method.upper()} {path}"
    generated_codes = routes[(path, method)]
    assert documented_codes <= generated_codes, (
        f"{operation_id}: códigos sin declarar en la app: {documented_codes - generated_codes}"
    )
    # FastAPI agrega 422 automáticamente a rutas con parámetros; el resto debe estar documentado.
    extra = generated_codes - documented_codes - {"422"}
    assert not extra, f"{operation_id}: códigos no documentados en el contrato: {extra}"
