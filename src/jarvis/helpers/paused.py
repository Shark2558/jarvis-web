# src/jarvis/helpers/paused.py
"""A helper his permission rows pause says so (integrated review M2; plan v11.0.4).

A morning job reads on "Allow" only (`jarvis.tools.background`). When one he switched on can't
read because of a row, he sees ONE fixed-template line, never anyone else's words:

    "Breach watching paused: your Email permission is set to Ask first. Set it to Allow to let
    it run by itself."

- `PauseCheck` is one reader's check: its helper is on for him (`on`) and the governed path's
  `verdict()` (what the job would be told now; no audit line) refuses. The row is named by its
  section on the Permissions page ("Email", "Contacts", "To-do list", "Calendar", "Weather and
  alerts", "Kitchen"), JARVIS's own word.
- Shown in that part's Helpers tab (`GET /v1/helpers`, `parts[].paused`), in the brief (one line
  at most in all, `fold`), and in `breach_status`. The audit chain already carries each refusal
  as a kind-only line ("breach_watch; ask first"), once a day.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from jarvis.core.guardrails import ActionRisk
from jarvis.logging import get_logger
from jarvis.permissions.groups import groups_for
from jarvis.tools.background import UNWIRED, BackgroundReads, Reason, Verdict

log = get_logger(__name__)

TIMEOUT_S = 2.0
MAX_PER_PART = 3
SEE_HELPERS = "see Helpers"


def row_word(tool: str) -> str:
    """The Permissions page's section for the row that covers `tool` ("" when none does)."""
    found = groups_for(tool, ActionRisk.READ_ONLY) if tool else []
    return found[0].section if found else ""


@dataclass(frozen=True)
class Pause:
    what: str  # JARVIS's own words for the helper: "Breach watching"
    row: str  # the row's section ("" when the rows couldn't be read at all)
    reason: Reason  # never "allowed"

    @property
    def line(self) -> str:
        if self.reason == "unreadable" or not self.row:
            return f"{self.what} paused: JARVIS couldn't read your permissions just now."
        if self.reason == "denied":
            return f"{self.what} paused: your {self.row} permission is set to Never."
        return (
            f"{self.what} paused: your {self.row} permission is set to Ask first. Set it to "
            "Allow to let it run by itself."
        )


def pause_of(what: str, v: Verdict) -> Pause | None:
    """The pause a verdict means for this helper (None: it reads)."""
    if v.ok:
        return None
    return Pause(what, row_word(v.tool) if v.reason != "unreadable" else "", v.reason)


@runtime_checkable
class PauseSource(Protocol):
    async def pause(self, uid: str) -> Pause | None: ...


class PauseCheck:
    """One background reader's pause. `on(uid)`: is the helper switched on for him (it raising
    means "can't tell": no line). `never_too=False`: a row on Never is his own "don't read this"
    for a reader with no switch of its own (his to-dos), so no line for it."""

    def __init__(
        self,
        reads: BackgroundReads | None,
        *,
        what: str,
        tools: tuple[str, ...],
        on: Callable[[str], Awaitable[bool]],
        never_too: bool = True,
    ) -> None:
        self._reads = reads
        self.what = what
        self.tools = tools
        self._on = on
        self._never_too = never_too

    async def pause(self, uid: str) -> Pause | None:
        try:
            if not await self._on(uid):
                return None
        except Exception as exc:  # noqa: BLE001 - can't tell whether it is on: say nothing
            log.warning("paused: switch unreadable", extra={"error": type(exc).__name__})
            return None
        v = await self._reads.verdict(uid, *self.tools) if self._reads is not None else UNWIRED
        if v.reason == "denied" and not self._never_too:
            return None
        return pause_of(self.what, v)


async def _one(src: PauseSource, uid: str) -> Pause | None:
    try:
        return await asyncio.wait_for(src.pause(uid), TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 - one check never fails a view or the brief
        log.warning("paused: a check failed", extra={"error": type(exc).__name__})
        return None


async def collect(sources: Sequence[PauseSource], uid: str) -> list[Pause]:
    found = await asyncio.gather(*(_one(s, uid) for s in sources))
    return [p for p in found if p is not None]


async def lines(sources: Sequence[PauseSource], uid: str) -> list[str]:
    """A part's lines for its Helpers tab (at most `MAX_PER_PART`)."""
    return [p.line for p in await collect(sources, uid)][:MAX_PER_PART]


def fold(pauses: Sequence[Pause]) -> str | None:
    """The brief's ONE line for every paused helper (None: nothing paused)."""
    if not pauses:
        return None
    if len(pauses) == 1:
        return pauses[0].line
    rows = ", ".join(dict.fromkeys(p.row for p in pauses if p.row))
    which = f" ({rows})" if rows else ""
    return f"Paused: {len(pauses)} helpers wait on your permissions{which}; {SEE_HELPERS}."


__all__ = [
    "MAX_PER_PART",
    "Pause",
    "PauseCheck",
    "PauseSource",
    "collect",
    "fold",
    "lines",
    "pause_of",
    "row_word",
]
