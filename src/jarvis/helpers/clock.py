# src/jarvis/helpers/clock.py
"""The helpers' two composite jobs (docs/plans/r11-free-helpers.md D3). No new Scheduler job.

- `helpers_clock`: the parts' 5-minute jobs (`kinds.CLOCK_JOBS`). With Home on it is added to the
  home watchdog (advisory there: never a 503 for the laptop check); with Home off the watchdog
  route runs it alone (`api/home.py`), so the one existing job serves both. It rides the morning
  tick too: the parts' jobs are idempotent (claims), so a run twice in a minute sends nothing twice,
  and reminders still come 04:00-11:30 if the 5-minute job was never made.
- `helpers_daily`: the morning tick's (`kinds.DAILY_JOBS`: the Gmail scans) plus I0's sweep of old
  send-log days.

Each composite runs its jobs through `ticks.run_jobs` inside its own budget, for the configured
owners (`ctx.owners`), never the watchdog's list of linked homes. A composite counts the jobs it
could not finish under `failed` (so the tick answer says "failed"), and every run of the clock
writes `{prefix}helpers_clock/status` (its time and each job's result, no owner data), which the
Helpers panel reads to say "Your 5-minute clock isn't running" when it is stale.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime

from jarvis.helpers.gate import GateStore
from jarvis.helpers.kinds import CLOCK_JOB, DAILY_JOB, SWEEP_JOB
from jarvis.logging import get_logger
from jarvis.notify.quiet import local
from jarvis.storage.docs import Docs, Set
from jarvis.ticks import FAILED_COUNT, TickJob, run_jobs

log = get_logger(__name__)

MARGIN_S = 1.0  # left for the composite's own bookkeeping inside its budget
DAILY_BUDGET_S = 40.0
STATUS = "helpers_clock"


class ClockStatus:
    """`{prefix}helpers_clock/status`: when the clock last ran and how each job did."""

    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self._docs = docs
        self._path = f"{prefix}helpers_clock/status"

    async def write(self, at: datetime, jobs: dict[str, str]) -> None:
        try:
            await self._docs.write([Set(self._path, {"at": at.isoformat(), "jobs": jobs})])
        except Exception as exc:  # noqa: BLE001 - bookkeeping only
            log.warning("helpers clock status not written", extra={"error": type(exc).__name__})

    async def read(self) -> dict[str, object] | None:
        try:
            return await self._docs.get(self._path)
        except Exception as exc:  # noqa: BLE001 - the panel says "unknown"
            log.warning("helpers clock status unreadable", extra={"error": type(exc).__name__})
            return None


class Composite:
    """One `TickJob` that runs several in its own budget for the configured owners."""

    def __init__(
        self,
        name: str,
        jobs: Sequence[TickJob],
        owners: tuple[str, ...],
        *,
        budget_s: float,
        now: Callable[[], datetime],
        status: ClockStatus | None = None,
    ) -> None:
        names = [j.name for j in jobs]
        if len(set(names)) != len(names):
            raise ValueError("helper job names must be unique")
        self.name = name
        self.budget_s = budget_s
        self._jobs = tuple(jobs)
        self._owners = owners
        self._now = now
        self._status = status
        self.last: dict[str, str] = {}

    @property
    def job_names(self) -> tuple[str, ...]:
        return tuple(j.name for j in self._jobs)

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        """`owners` (the caller's list) is ignored: the helpers serve the configured owners."""
        inner = max(1.0, self.budget_s - MARGIN_S)
        results = dict(await run_jobs(self._jobs, self._owners, total_budget_s=inner))
        self.last = dict(results)
        if self._status is not None:
            await self._status.write(self._now(), dict(results))
        failed = sum(1 for r in results.values() if r == "failed")
        return {"jobs": len(results), "ok": len(results) - failed, FAILED_COUNT: failed}


class SweepJob:
    """I0's own daily job: send-log days older than `gate.KEEP_DAYS`."""

    name = SWEEP_JOB
    budget_s = 10.0

    def __init__(self, store: GateStore, *, tz: str, now: Callable[[], datetime]) -> None:
        self._store = store
        self._tz = tz
        self._now = now

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        today = local(self._now(), self._tz).date().isoformat()
        return {"swept": await self._store.sweep(tuple(owners), today)}


def clock_composite(
    jobs: Sequence[TickJob],
    owners: tuple[str, ...],
    *,
    budget_s: float,
    now: Callable[[], datetime],
    status: ClockStatus,
) -> Composite:
    return Composite(CLOCK_JOB, jobs, owners, budget_s=budget_s, now=now, status=status)


def daily_composite(
    jobs: Sequence[TickJob], owners: tuple[str, ...], *, now: Callable[[], datetime]
) -> Composite:
    return Composite(DAILY_JOB, jobs, owners, budget_s=DAILY_BUDGET_S, now=now)


__all__ = [
    "DAILY_BUDGET_S",
    "STATUS",
    "ClockStatus",
    "Composite",
    "SweepJob",
    "clock_composite",
    "daily_composite",
]
