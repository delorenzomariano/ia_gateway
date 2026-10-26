"""Validación de cuerpos de respuesta contra los esquemas de contracts/openapi.yaml."""

from functools import cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

# Contrato vigente: v1.1.0 de la feature 002 (amplía de forma compatible el de 001).
CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "specs" / "002-chat-image-ocr" / "contracts"
_SPEC_URI = "urn:ia-gateway:openapi"


@cache
def load_openapi() -> dict[str, Any]:
    with (CONTRACTS_DIR / "openapi.yaml").open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@cache
def _registry() -> Registry:
    resource = Resource(contents=load_openapi(), specification=DRAFT202012)
    return Registry().with_resource(_SPEC_URI, resource)


def assert_matches_schema(body: Any, schema_name: str) -> None:
    """Falla si `body` no cumple `components.schemas.<schema_name>`."""
    schema = {"$ref": f"{_SPEC_URI}#/components/schemas/{schema_name}"}
    validator = Draft202012Validator(schema, registry=_registry(), format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(body), key=lambda e: list(e.path))
    if errors:
        details = "; ".join(f"{list(e.path)}: {e.message}" for e in errors)
        raise AssertionError(f"La respuesta no cumple {schema_name}: {details}")
