# src/jarvis/coach/water.py
"""R8 builder D, row 248 (docs/plans/r8-vision.md v8.0.4 section 2.1; seam S11's `WaterLog`): the
desk webcam's water counter adds a glass to his EXISTING water log, with Undo.

The console's `water` use case (console-coach-water.js) counts sips and turns every few sips into a
glass; the Desk pane, on each new glass, calls `add_glass` (through the route I1 mounts) and shows
Undo with the id it gets back. `add_glass` is `helpers.nudges.hydrate.log_water(svc, uid, 1)`, the
very call the Helpers panel and the brain's tool make, so the glass lands in the same sealed
`wellbeing` day (no keyring: `WellbeingOff`, the log is off, never written in clear). `undo` takes
that one glass off the day it was added to (never below 0), once, by its owner, within `UNDO_S`.

The Undo ids live in this process's memory only, at most `PENDING_MAX` of them: an Undo after a
restart (or after `UNDO_S`) answers False and he takes the glass off by hand in Helpers. A count is
never put in a log line (the helpers' rule).
"""

from __future__ import annotations

import secrets
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

from jarvis.helpers.nudges import hydrate
from jarvis.helpers.nudges.service import NudgeService
from jarvis.helpers.nudges.store import WellDay

UNDO_S = 10 * 60  # an Undo is offered for ten minutes
PENDING_MAX = 50
UNDO_ID = "wu_"


@dataclass(frozen=True)
class _Pending:
    uid: str
    day: str  # yyyy-mm-dd in his zone: the day the glass was added to
    until: float  # unix seconds


def _one_less(day: WellDay) -> WellDay:
    return day.model_copy(update={"water": max(0, day.water - 1)})


class CoachWaterLog:
    """`jarvis.coach.ports.WaterLog` over the helpers' water log."""

    def __init__(self, svc: NudgeService, *, clock: Callable[[], float] = time.time) -> None:
        self._svc = svc
        self._clock = clock
        self._pending: OrderedDict[str, _Pending] = OrderedDict()

    def _prune(self) -> None:
        now = self._clock()
        for key in [k for k, p in self._pending.items() if p.until <= now]:
            del self._pending[key]
        while len(self._pending) > PENDING_MAX:
            self._pending.popitem(last=False)

    async def add_glass(self, uid: str) -> str:
        """Logs one glass in today's water log; returns the Undo id (raises as `log_water` does)."""
        day = self._svc.day_of().isoformat()
        await hydrate.log_water(self._svc, uid, 1)
        undo_id = f"{UNDO_ID}{secrets.token_hex(6)}"
        self._pending[undo_id] = _Pending(uid, day, self._clock() + UNDO_S)
        self._prune()
        return undo_id

    async def undo(self, uid: str, undo_id: str) -> bool:
        """Takes that glass off again: True once; False for an unknown, spent, expired or another
        owner's id (nothing changes)."""
        self._prune()
        found = self._pending.get(undo_id) if isinstance(undo_id, str) else None
        if found is None or found.uid != uid:
            return False
        del self._pending[undo_id]  # spent before the write: a second Undo can't take two
        await self._svc.well.change(uid, found.day, _one_less)
        return True


__all__ = ["PENDING_MAX", "UNDO_S", "CoachWaterLog"]
