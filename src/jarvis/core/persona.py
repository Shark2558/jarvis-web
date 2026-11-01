# src/jarvis/core/persona.py
"""The persona for one turn (Layer 4 → 8; slice 9 D8): the owner's wit level picks one of three
stable, cacheable system prompts (`jarvis.core.prompts`).

The level comes from the owner's voice settings (`WitSource`, cached by the implementation). It is
a nicety: any failure, an unknown level or a read slower than `WIT_READ_TIMEOUT_S` gives the
default ("film"), never a failed or delayed reply. The Brain asks once per turn and sends the
same prompt with every model call of that turn.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from jarvis.core.prompts import DEFAULT_WIT, WIT_IDS, build_system_prompt
from jarvis.logging import get_logger

log = get_logger(__name__)

WIT_READ_TIMEOUT_S = 1.5  # the owner's wit level is a nicety: never hold a reply for it


class WitSource(Protocol):
    """The owner's wit level (slice 9 D8): the voice settings, cached by the implementation."""

    async def wit_for(self, user_id: str) -> str: ...


class Persona:
    """Three system prompts built once; `system_for` picks the owner's."""

    def __init__(self, *, honorific: str, wit: WitSource | None) -> None:
        self.wit = wit
        self._systems = {w: build_system_prompt(honorific=honorific, wit=w) for w in WIT_IDS}
        self.default = self._systems[DEFAULT_WIT]

    async def system_for(self, user_id: str) -> str:
        """The system prompt for the owner's wit level; the default on any failure."""
        if self.wit is None:
            return self.default
        try:
            wit = await asyncio.wait_for(self.wit.wit_for(user_id), WIT_READ_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 — a persona nicety never fails a reply
            log.warning(
                "wit level unreadable; using the default", extra={"reason": type(exc).__name__}
            )
            return self.default
        return self._systems.get(wit, self.default)


__all__ = ["WIT_READ_TIMEOUT_S", "Persona", "WitSource"]
