# src/jarvis/llm/fallback.py
"""The fallback brain's contract and its safety limits (R1 D10-D12; Layer 4 graceful degradation).

When the cloud brain is UNREACHABLE (`LLMUnreachable`: connection error, timeout, 5xx) the router
hands the same call to a fallback brain: Ollama on the owner's laptop. This module holds what the
router and the laptop service share and nothing that talks to the network:

- `FallbackBrain`: the Protocol the router calls (`jarvis.offline.service.LocalFallback` is the
  implementation). It reports `ready()`, completes, streams, and is told when the cloud answers.
- `OFFLINE_TOOLS`: the only tools the laptop brain is offered (<= 12, no R3). A small model picks
  arguments less reliably and is easier to steer with injected text, so everything else is
  withheld, and a call to anything else is dropped ("I can't do that in offline mode").
- `OFFLINE_NOTE`: the trailer added to the prompt of an offline turn.
- `Breaker`: after a cloud miss answered by the laptop, the next two minutes skip the cloud.
- `FallbackFailed`: the cloud AND the laptop failed; says so in plain words, no vendor text.

Writes made during an offline turn become one-tap cards in `jarvis.offline.rules.OfflineRules`.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Protocol

from jarvis.llm.base import (
    ChatMessage,
    Completion,
    Effort,
    LLMUnreachable,
    StreamUsage,
    ToolSpec,
)

if TYPE_CHECKING:
    from jarvis.llm.router import ModelTier

# The laptop brain is offered these tools and no others (plan D11 a). All are R1 reads or R2 writes;
# no send, no delete, nothing irreversible.
OFFLINE_TOOLS: tuple[str, ...] = (
    "calendar_list_events",
    "calendar_free_slots",
    "reminders_list",
    "reminder_add",
    "tasks_list",
    "task_add",
    "task_complete",
    "grocery_list",
    "grocery_add",
    "grocery_remove",
    "gmail_unread_digest",
    "gmail_track_packages",
)

OFFLINE_NOTE = (
    "Offline mode: you are running on the owner's laptop; fewer tools; every change asks first; "
    "keep answers short."
)
CANT_OFFLINE = "I can't do that in offline mode."
FALLBACK_FAILED_TEXT = "Claude can't be reached and your laptop didn't answer."
BREAKER_S = 120.0  # D12: after a cloud miss, this long straight to the laptop, then one cloud try


class FallbackFailed(LLMUnreachable):
    """The cloud was unreachable and the laptop did not answer either. A subclass of
    `LLMUnreachable` so code that catches the family still does; the message is ours, never the
    vendor's (the console shows it as is)."""

    def __init__(self, message: str = FALLBACK_FAILED_TEXT) -> None:
        super().__init__(message)


class FallbackBrain(Protocol):
    """What `ModelRouter` needs from a fallback brain. `tier` is the tier the caller asked for;
    the fallback maps it to its one model. Errors it raises mean "the laptop did not answer"."""

    async def ready(self) -> bool:
        """Configured and switched on right now (read per call; cheap)."""
        ...

    async def complete(
        self,
        *,
        tier: ModelTier,
        system: str,
        system_dynamic: str | None,
        messages: list[ChatMessage],
        max_tokens: int,
        effort: Effort | None,
        tools: list[ToolSpec] | None,
    ) -> Completion: ...

    def stream(
        self,
        *,
        tier: ModelTier,
        system: str,
        system_dynamic: str | None,
        messages: list[ChatMessage],
        max_tokens: int,
        effort: Effort | None,
        usage: StreamUsage | None,
    ) -> AsyncIterator[str]: ...

    async def cloud_ok(self) -> None:
        """The cloud brain answered (the router calls this after every cloud success)."""
        ...


class Breaker:
    """Open for `BREAKER_S` seconds after `trip()`. Not thread-safe (one event loop)."""

    def __init__(
        self, *, seconds: float = BREAKER_S, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._seconds = seconds
        self._clock = clock
        self._until = 0.0

    def trip(self) -> None:
        self._until = self._clock() + self._seconds

    def reset(self) -> None:
        self._until = 0.0

    def is_open(self) -> bool:
        return self._clock() < self._until


def offline_tools(tools: list[ToolSpec] | None) -> list[ToolSpec] | None:
    """The offered tools that the laptop may use; None when the turn had none (or none allowed)."""
    if not tools:
        return None
    kept = [t for t in tools if t.name in OFFLINE_TOOLS]
    return kept or None


def offline_trailer(system_dynamic: str | None) -> str:
    return f"{system_dynamic}\n\n{OFFLINE_NOTE}" if system_dynamic else OFFLINE_NOTE


def confine(completion: Completion, offered: list[ToolSpec] | None) -> Completion:
    """The laptop's answer, marked offline and metered at zero. A tool call for anything not
    offered is dropped; when nothing is left the owner is told why in plain words."""
    allowed = {t.name for t in offered or []}
    kept = [c for c in completion.tool_calls if c.name in allowed]
    text = completion.text
    if len(kept) < len(completion.tool_calls) and not kept:
        text = f"{text}\n\n{CANT_OFFLINE}".strip()
    return completion.model_copy(
        update={
            "tool_calls": kept,
            "text": text,
            "offline": True,
            "cost_usd": 0.0,
            "stop_reason": "tool_use" if kept else "end_turn",
        }
    )


__all__ = [
    "BREAKER_S",
    "CANT_OFFLINE",
    "FALLBACK_FAILED_TEXT",
    "OFFLINE_NOTE",
    "OFFLINE_TOOLS",
    "Breaker",
    "FallbackBrain",
    "FallbackFailed",
    "confine",
    "offline_tools",
    "offline_trailer",
]
