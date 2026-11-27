# src/jarvis/calls/retention.py
"""The calls' retention job (R18 A1; docs/plans/r18-calls.md section 4 step 8 and 7 item 3;
BUILD-BRIEF.md "Records": kept 30 days, a setting; Layer 7 housekeeping on the scheduler tick).

`CallRetentionJob` is a `jarvis.ticks.TickJob` (I1 adds it to `app.state.tick_jobs`). For each
owner it deletes, through `RecordKeeper.delete` (every sealed part, then the record, audited), the
calls whose time is up and that he did not Keep: those past their own `retention_days` (the
store's `due_for_deletion`) and those past his current setting, when he lowered it since. It
never raises: one owner's failure is counted under `failed` (the tick then reports the job
failed) and stops no one; it stops early when the tick's time runs out (`ticks.time_left`) and
the rest waits for the next tick.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

from jarvis.calls.ports import CallStore
from jarvis.calls.records import RecordKeeper
from jarvis.logging import get_logger
from jarvis.ticks import FAILED_COUNT, time_left

log = get_logger(__name__)

JOB_NAME = "calls_retention"
BUDGET_S = 30.0
SCAN_LIMIT = 200
MIN_LEFT_S = 2.0


def _utcnow() -> datetime:
    return datetime.now(UTC)


class CallRetentionJob:
    name = JOB_NAME
    budget_s = BUDGET_S

    def __init__(
        self, store: CallStore, keeper: RecordKeeper, *, clock: Callable[[], datetime] = _utcnow
    ) -> None:
        self.store, self.keeper, self._clock = store, keeper, clock

    async def _due(self, uid: str, now: datetime) -> list[str]:
        days = (await self.store.settings(uid)).retention_days
        cut = now - timedelta(days=days)
        due = [r.id for r in await self.store.due_for_deletion(uid, now)]
        for r in await self.store.list_records(uid, limit=SCAN_LIMIT):
            if not r.keep and r.started_at <= cut and r.id not in due:
                due.append(r.id)
        return due

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        now = self._clock()
        deleted = failed = 0
        for uid in owners:
            try:
                for call_id in await self._due(uid, now):
                    left = time_left()
                    if left is not None and left < MIN_LEFT_S:
                        return {"deleted": deleted, FAILED_COUNT: failed}
                    if await self.keeper.delete(uid, call_id, why="retention"):
                        deleted += 1
            except Exception as exc:  # noqa: BLE001 - one owner never stops the others
                log.error("call retention failed for an owner", extra={"error": type(exc).__name__})
                failed += 1
        return {"deleted": deleted, FAILED_COUNT: failed}


__all__ = ["BUDGET_S", "JOB_NAME", "CallRetentionJob"]
