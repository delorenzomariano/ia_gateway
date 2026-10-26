"""Contenedor de servicios compartidos y su dependencia FastAPI."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from ia_gateway.chat.images import ImageReader
from ia_gateway.chat.locks import GenerationLocks
from ia_gateway.chat.orchestrator import ChatOrchestrator
from ia_gateway.config import Settings
from ia_gateway.llm.base import LLMClient
from ia_gateway.ocr.base import OcrEngine
from ia_gateway.storage.repository import ConversationRepository


@dataclass
class Services:
    settings: Settings
    repository: ConversationRepository
    llm: LLMClient
    locks: GenerationLocks
    orchestrator: ChatOrchestrator
    ocr: OcrEngine
    image_reader: ImageReader


def get_services(request: Request) -> Services:
    return request.app.state.services
