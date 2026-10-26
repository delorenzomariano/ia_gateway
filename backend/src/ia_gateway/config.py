"""Configuración del backend: variables de entorno con prefijo IA_GATEWAY_."""

from __future__ import annotations

import math
from datetime import timedelta
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_SYSTEM_PROMPT = (
    "Sos un asistente útil, claro y conciso. Respondé en español rioplatense neutro, "
    "usando párrafos cortos, listas o bloques de código cuando ayuden a la lectura. "
    "Si no sabés algo, decilo en lugar de inventarlo."
)

CommaList = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="IA_GATEWAY_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:4b"
    # None = no enviar `think` (lo decide el modelo). Con qwen3 en Ollama 0.40, `think: false`
    # no desactiva el razonamiento: lo mezcla en el contenido y es más lento (ver research.md R3).
    ollama_think: bool | None = None
    ollama_num_ctx: int = Field(default=8192, gt=0)

    system_prompt: str = DEFAULT_SYSTEM_PROMPT

    # Límites
    max_message_chars: int = Field(default=4000, gt=0)
    context_char_budget: int = Field(default=24000, gt=0)
    retention_hours: float = Field(default=24, gt=0)
    cleanup_interval_minutes: float = Field(default=10, gt=0)

    # Timeouts (segundos)
    timeout_connect_s: float = Field(default=5, gt=0)
    timeout_first_chunk_s: float = Field(default=60, gt=0)
    timeout_idle_s: float = Field(default=30, gt=0)
    timeout_total_s: float = Field(default=180, gt=0)

    # Streaming
    sse_ping_interval_s: float = Field(default=15, gt=0)

    # Herramientas
    max_tool_rounds: int = Field(default=5, ge=1)
    tools_enabled: CommaList = []

    # Imágenes: reconocimiento de texto (OCR) con Tesseract
    ocr_enabled: bool = True
    ocr_tesseract_cmd: str = ""
    ocr_languages: str = "spa+eng"
    ocr_max_image_bytes: int = Field(default=5_242_880, gt=0)
    ocr_max_pixels: int = Field(default=25_000_000, gt=0)
    ocr_max_text_chars: int = Field(default=8000, gt=0)
    ocr_min_confidence: float = Field(default=50, ge=0, le=100)
    ocr_timeout_s: float = Field(default=30, gt=0)
    ocr_max_concurrency: int = Field(default=2, ge=1)

    # Acceso (sin autenticación en v1: solo red local)
    allowed_origins: CommaList = ["http://localhost:8000", "http://127.0.0.1:8000"]
    allowed_networks: CommaList = [
        "127.0.0.0/8",
        "::1/128",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
    ]

    # Almacenamiento y servidor
    database_path: str = "data/ia_gateway.db"
    serve_frontend: bool = True

    # Observabilidad
    diagnostic_mode: bool = False
    log_level: str = "INFO"

    @field_validator("tools_enabled", "allowed_origins", "allowed_networks", mode="before")
    @classmethod
    def _split_commas(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("ollama_think", mode="before")
    @classmethod
    def _blank_think_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("system_prompt", mode="before")
    @classmethod
    def _default_prompt_if_blank(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return DEFAULT_SYSTEM_PROMPT
        return value

    @property
    def retention(self) -> timedelta:
        return timedelta(hours=self.retention_hours)

    @property
    def max_request_body_bytes(self) -> int:
        """Imagen máxima en base64 más margen para el resto del JSON (research.md R3)."""
        return math.ceil(self.ocr_max_image_bytes / 3) * 4 + 65_536
