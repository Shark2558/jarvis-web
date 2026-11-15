# src/jarvis/wardrobe/catalog/pilot.py
"""The pilot's counts (docs/plans/r13-wardrobe.md "Tests and evals", e2e 8; owner question 14):
counts only, never a piece, from his ledger.

- scans with a candidate: events whose evidence carries the first candidate's score; the first
  candidate chosen: those whose `how` is `match` (the phone sends `match` when his tap took
  candidate 1, `tap` with that score when he took another);
- wrong status changes: corrections of state-setting events; events: every event;
- suggested / unavailable suggested: Part C's plan log (`plan_counts`, joined at I1; 0 until then).
The pass line: unavailable pieces suggested = 0 and at most 1 wrong status change in 50 events.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from jarvis.wardrobe.catalog.store import CatalogStore
from jarvis.wardrobe.http import Pilot
from jarvis.wardrobe.states import STATE_SETTING

PlanCounts = Callable[[str], Awaitable[tuple[int, int]]]


def passes(p: Pilot) -> bool:
    return p.unavailable_suggested == 0 and p.state_corrections * 50 <= max(p.events, 50)


class PilotCounts:
    def __init__(self, store: CatalogStore, plan_counts: PlanCounts | None = None) -> None:
        self.store, self._plans = store, plan_counts

    async def counts(self, uid: str) -> Pilot:
        view = await self.store.view(uid)
        scored = chosen = events = corrections = 0
        for pid in view.pieces:
            log = await self.store.events(uid, pid)
            kinds = {e.id: e.kind for e in log}
            events += len(log)
            for e in log:
                if e.evidence.score is not None:
                    scored += 1
                    chosen += e.evidence.how == "match"
                if e.kind == "corrected" and kinds.get(e.voids or "") in STATE_SETTING:
                    corrections += 1
        suggested, unavailable = await self._plans(uid) if self._plans is not None else (0, 0)
        return Pilot(
            scans_with_candidate=scored, first_candidate_chosen=chosen, events=events,
            state_corrections=corrections, suggested=suggested,
            unavailable_suggested=unavailable,
        )  # fmt: skip


__all__ = ["PilotCounts", "PlanCounts", "passes"]
