# src/jarvis/health/tick.py
"""The scheduled health check as a TickJob (R4 D14). Rides the existing tick: no new Cloud
Scheduler job. Owners are checked in parallel (bounded), each forced fresh. One owner's failure
is counted under `failed` and stops no one; so is an owner still unserved at the job's own
deadline, or one whose result could not be saved.

Cadence (R5.1 D4): ONE instance of this job rides both the morning tick (`0,30 4-11`) and the
5-minute home watchdog (`Watchdog(..., extra=(..., job))`), so the check runs around the clock
for every owner with a linked home, and at most once per `CHECK_EVERY_S` (15 minutes) per owner:
the per-owner gate below is the instance's own, shared by both callers (in memory; a restart
simply checks once early). The gate is taken before any await, so two callers at the same
moment check an owner once. Owners without a linked home are checked by the morning tick only
(the watchdog runs over linked homes) and on demand (`systems_check`, the pop-up)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence

from jarvis.health.service import HealthService
from jarvis.logging import get_logger
from jarvis.ticks import FAILED_COUNT

log = get_logger(__name__)

TICK_BUDGET_S = 30.0
TICK_DEADLINE_S = 40.0  # stop waiting before the tick cancels us, so the count is still returned
MAX_PARALLEL_OWNERS = 8
CHECK_EVERY_S = 900.0  # R5.1 D4: at most one scheduled check per owner per 15 minutes
OWNERS_COUNT = "owners"
FAULTS_COUNT = "faults"


class HealthTickJob:
    name = "health_check"
    budget_s = TICK_BUDGET_S

    def __init__(
        self,
        svc: HealthService,
        *,
        deadline_s: float = TICK_DEADLINE_S,
        every_s: float = CHECK_EVERY_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._svc = svc
        self._deadline_s = deadline_s
        self._every_s, self._clock = every_s, clock
        self._last: dict[str, float] = {}

    def _due(self, owners: Sequence[str]) -> list[str]:
        """The owners not checked within `every_s`; marks them as attempted now."""
        now = self._clock()
        due = [u for u in owners if now - self._last.get(u, float("-inf")) >= self._every_s]
        self._last.update(dict.fromkeys(due, now))
        return due

    async def _one(self, uid: str, gate: asyncio.Semaphore) -> tuple[bool, bool]:
        """(failed, faulty) for one owner."""
        async with gate:
            try:
                report = await self._svc.check(uid, force=True)
            except Exception as exc:  # noqa: BLE001 - one owner never stops the others
                log.error("health check failed for an owner", extra={"error": type(exc).__name__})
                return True, False
        return (not report.persisted), report.overall != "ok"

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        owners = self._due(owners)
        if not owners:
            return {OWNERS_COUNT: 0, FAULTS_COUNT: 0, FAILED_COUNT: 0}
        gate = asyncio.Semaphore(MAX_PARALLEL_OWNERS)
        tasks = [asyncio.ensure_future(self._one(uid, gate)) for uid in owners]
        try:
            _, pending = await asyncio.wait(tasks, timeout=self._deadline_s)
        except BaseException:
            for t in tasks:
                t.cancel()
            raise
        for t in pending:
            t.cancel()
        counts = {OWNERS_COUNT: len(tasks), FAULTS_COUNT: 0, FAILED_COUNT: len(pending)}
        for t in tasks:
            if t in pending:
                continue
            failed, faulty = t.result()
            counts[FAILED_COUNT] += int(failed)
            counts[FAULTS_COUNT] += int(faulty)
        if pending:
            log.error("health check ran out of time", extra={"unserved": len(pending)})
        return counts


__all__ = [
    "CHECK_EVERY_S",
    "FAULTS_COUNT",
    "MAX_PARALLEL_OWNERS",
    "OWNERS_COUNT",
    "TICK_BUDGET_S",
    "TICK_DEADLINE_S",
    "HealthTickJob",
]
