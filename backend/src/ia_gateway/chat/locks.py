"""A lo sumo una generación en curso por conversación (en memoria del proceso)."""

from __future__ import annotations

from collections.abc import Callable


class GenerationInProgressError(Exception):
    pass


class GenerationLocks:
    def __init__(self) -> None:
        self._busy: set[str] = set()

    def acquire(self, conversation_id: str) -> Callable[[], None]:
        """Toma el lock o lanza GenerationInProgressError; devuelve la función que lo libera."""
        if conversation_id in self._busy:
            raise GenerationInProgressError(conversation_id)
        self._busy.add(conversation_id)
        released = False

        def release() -> None:
            nonlocal released
            if not released:
                released = True
                self._busy.discard(conversation_id)

        return release

    def is_busy(self, conversation_id: str) -> bool:
        return conversation_id in self._busy
