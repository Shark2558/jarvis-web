# src/jarvis/helpers/nudges/jobs.py
"""Part C's two jobs on the 5-minute clock (docs/plans/r11-free-helpers.md D3; `kinds.CLOCK_JOBS`):

- `nudges`: stand-up (and its meeting variant), water, focus and free time.
- `activity_check`: a planned activity that had no check-in (item 11).

Each runs for the configured owners (`ctx.owners`; the `owners` argument is ignored), one read of
his settings per run, an outside read only when a nudge that needs it is due (the calendar is
cached, `calendar.Agenda`), and every nudge through `NudgeService.deliver` (claim, send, release
on retry): idempotent, so a second run in the same minute or a restart sends nothing twice. One
owner's failure stops no one (counted under `failed`). The counts are outcomes, never a glass of
water or a word he typed. `activity_check` also sweeps his sealed log's old days once a day.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import datetime

from jarvis.helpers.nudges import activity, focus, freetime, hydrate, standup
from jarvis.helpers.nudges.models import NudgeSettings
from jarvis.helpers.nudges.service import NudgeService, Plan
from jarvis.logging import get_logger
from jarvis.ticks import FAILED_COUNT

log = get_logger(__name__)

JOB_BUDGET_S = 8.0
SWEEP = "sweep"  # the sealed log's daily sweep claim


async def _nudge_plans(svc: NudgeService, uid: str, s: NudgeSettings, now: datetime) -> list[Plan]:
    return [
        *await standup.plans(svc, uid, s, now),
        *hydrate.plans(svc, s, now),
        *focus.plans(svc, uid, s, now),
        *freetime.plans(svc, uid, s, now),
    ]


class _Job:
    name = ""
    budget_s = JOB_BUDGET_S

    def __init__(self, svc: NudgeService, owners: tuple[str, ...]) -> None:
        self._svc = svc
        self._owners = owners

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        counts: Counter[str] = Counter()
        for uid in self._owners:
            try:
                for word in await self._owner(uid):
                    counts[word.split(":")[0]] += 1
            except Exception as exc:  # noqa: BLE001 - one owner never stops the others
                log.warning("a nudge job failed for an owner", extra={"error": type(exc).__name__})
                counts[FAILED_COUNT] += 1
        return dict(counts)

    async def _owner(self, uid: str) -> list[str]:
        svc = self._svc
        s = await svc.settings(uid)
        if not s.active():
            return []
        now = svc.now()
        return [await svc.deliver(uid, p) for p in await self._plans(uid, s, now)]

    async def _plans(self, uid: str, s: NudgeSettings, now: datetime) -> list[Plan]:
        raise NotImplementedError


class NudgesJob(_Job):
    name = "nudges"

    async def _plans(self, uid: str, s: NudgeSettings, now: datetime) -> list[Plan]:
        return await _nudge_plans(self._svc, uid, s, now)


class ActivityJob(_Job):
    name = "activity_check"

    async def _plans(self, uid: str, s: NudgeSettings, now: datetime) -> list[Plan]:
        return await activity.plans(self._svc, uid, s, now)

    async def _owner(self, uid: str) -> list[str]:
        if self._svc.well.on:
            await self._sweep(uid)
        return await super()._owner(uid)

    async def _sweep(self, uid: str) -> None:
        """The sealed log's days past 30, at most once a local day (a claim, like a nudge). A
        failed sweep is logged by class name and its claim released: the asks still run, and the
        next run sweeps again."""
        svc = self._svc
        today = svc.day_of().isoformat()
        if not await svc.store.claim(uid, today, SWEEP):
            return
        try:
            await svc.well.sweep(uid, today)
        except Exception as exc:  # noqa: BLE001 - old days wait for the next run, the asks go on
            log.warning("nudges: the sweep failed", extra={"error": type(exc).__name__})
            await svc.store.release(uid, today, SWEEP)


__all__ = ["JOB_BUDGET_S", "ActivityJob", "NudgesJob"]
