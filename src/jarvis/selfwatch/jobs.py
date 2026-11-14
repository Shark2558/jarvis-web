# src/jarvis/selfwatch/jobs.py
"""Part B's watch and its two jobs (docs/plans/r14-hardening.md D5, D7, review A6).

`Watch` holds what the self-health watch knows (the job ledger, the clocks, the errors handler,
the once-only claims) and the tick observer (`observe`, synchronous, never raises). Its jobs:

- `selfwatch_clock` (5 minutes, advisory, FIRST on both 5-minute paths, for the brief's owners):
  the 5-minute clock's stamp and the morning clock's check, the error counts written, the job
  streaks, the errors, the brief, a new version.
- `selfwatch_daily` (the morning tick, after the other jobs): the morning clock's stamp and the
  5-minute clock's check, the job streaks, and once a day the spend snapshot and the sweeps.

Each step stands alone: one that fails is logged as a class name and counted under `failed`
(the job's own streak, which the OTHER job reports: a selfwatch job never reports itself), and
the rest still run. Job failures go out as ONE `job_failing` naming every job in a streak, at
most one an hour per owner (`JOB_ALERT_EVERY`), each streak once; errors piling up are not said
while a told streak is still going (the same incident, said once).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from jarvis.config import Settings
from jarvis.logging import get_logger
from jarvis.notify.ports import Notifier
from jarvis.selfwatch import errors as errs
from jarvis.selfwatch import texts
from jarvis.selfwatch.brief_check import BriefCheck, BriefLike
from jarvis.selfwatch.clocks import Clocks, ClockState, Event, on_tick, on_watchdog
from jarvis.selfwatch.deploys import DeployWatch
from jarvis.selfwatch.errors import ErrorCounter
from jarvis.selfwatch.ledger import JobLedger, Streak, Told
from jarvis.selfwatch.spend import BillingLike, SpendWatch
from jarvis.storage.docs import Docs
from jarvis.ticks import FAILED_COUNT, JobOutcome
from jarvis.undo.store import owner_ok

log = get_logger(__name__)

CLOCK_NAME = "selfwatch_clock"
DAILY_NAME = "selfwatch_daily"
CLOCK_BUDGET_S = 15.0  # it runs first in the watchdog's 50 s
DAILY_BUDGET_S = 25.0
JOB_ALERT_EVERY = timedelta(hours=1)  # A6: one aggregated `job_failing` an hour per owner
Done = tuple[int, bool]  # (alerts sent, whether the step's documents were kept)
Step = Callable[[Sequence[str], datetime, str], Awaitable[Done]]


def job_alerts(names: Sequence[str]) -> list[tuple[str, tuple[str, ...]]]:
    """(subject, jobs) of each `job_failing` alert: ONE naming every job in a streak (A6)."""
    return [("jobs", tuple(names))] if names else []


def _streak_id(name: str, s: Streak) -> str:
    return f"{name}@{s.since.isoformat()}"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Watch:
    def __init__(
        self,
        s: Settings,
        docs: Docs,
        *,
        notifier: Callable[[], Notifier | None],
        brief: Callable[[], BriefLike | None],
        billing: Callable[[], BillingLike | None],
        version: str,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        p = s.firestore_prefix
        self.docs, self.now, self.version, self.prefix = docs, now, version, p
        self.tz = ZoneInfo(s.user_timezone)
        self.streak, self.errors_limit = s.selfwatch_fail_streak, s.selfwatch_errors_per_hour
        self.factor = s.selfwatch_spike_factor
        self.ledger = JobLedger(prefix=p)
        self.clocks = Clocks(prefix=p)
        self.errors = ErrorCounter(tz=self.tz, prefix=p)
        self.told = Told(docs, prefix=p)
        self.teller = texts.Teller(notifier, self.told)
        grace = timedelta(minutes=s.selfwatch_brief_grace_min)
        self.briefs = BriefCheck(brief, grace=grace, tz=self.tz)
        self.spend = SpendWatch(
            billing, tz=self.tz, factor=self.factor, min_inr=s.selfwatch_spike_min_inr, prefix=p
        )
        self.deploys = DeployWatch(revision=s.cloud_run_revision, version=version, prefix=p)
        self._day_done: str | None = None
        self.clock_job = _Job(CLOCK_NAME, CLOCK_BUDGET_S, self, self._clock_steps())
        self.daily_job = _Job(DAILY_NAME, DAILY_BUDGET_S, self, self._daily_steps())

    def _clock_steps(self) -> tuple[Step, ...]:
        return (
            self.load,
            self.watchdog_beat,
            self.errors_step,
            self.report_jobs,
            self.briefs_step,
            self.deploy_step,
        )

    def _daily_steps(self) -> tuple[Step, ...]:
        return (self.load, self.tick_beat, self.report_jobs, self.once_a_day)

    def observe(self, outcome: JobOutcome) -> None:
        """The tick observer (`ticks.TickObserver`): synchronous, in memory, never raises."""
        try:
            at = self.now()
            self.ledger.observe(outcome.name, outcome.outcome, at)
            self.clocks.seen(outcome.clock, at)
        except Exception:  # noqa: BLE001 - watching a job never stops it, nor logs about it
            return

    async def run_steps(
        self, me: str, owners: Sequence[str], steps: Sequence[Step]
    ) -> dict[str, int]:
        now = self.now()
        owners = tuple(u for u in owners if isinstance(u, str) and owner_ok(u))
        counts = {"owners": len(owners), "told": 0, FAILED_COUNT: 0}
        for step in steps:
            try:
                told, kept = await step(owners, now, me)
            except Exception as exc:  # noqa: BLE001 - one step never stops the others
                log.warning(
                    "selfwatch step failed",
                    extra={"job": me, "step": step.__name__, "error": type(exc).__name__},
                )
                told, kept = 0, False
            counts["told"] += told
            counts[FAILED_COUNT] += int(not kept)
        try:
            await self.ledger.flush(self.docs)
        except Exception as exc:  # noqa: BLE001
            log.warning("selfwatch ledger not kept", extra={"error": type(exc).__name__})
            counts[FAILED_COUNT] += 1
        return counts

    # ---- the steps: each answers (alerts sent, documents kept) ---------------------------------
    async def load(self, owners: Sequence[str], now: datetime, me: str) -> Done:
        await self.ledger.load(self.docs)
        return 0, self.ledger.loaded

    async def _clock_events(
        self,
        owners: Sequence[str],
        now: datetime,
        beat: Callable[[ClockState, datetime, ZoneInfo], tuple[ClockState, list[Event]]],
    ) -> Done:
        events: list[Event] = []

        def change(s: ClockState) -> ClockState:
            new, got = beat(s, now, self.tz)
            events[:] = got
            return new

        _, kept = await self.clocks.update(self.docs, change)
        told = 0
        for e in events:
            if e.kind == "clock_stopped":
                text = texts.clock_stopped(e.clock, e.at)
            else:
                text = texts.clock_back(e.clock)
            told += await self.teller.tell(owners, e.kind, e.cause, text, now, subject=e.clock)
        return told, kept

    async def watchdog_beat(self, owners: Sequence[str], now: datetime, me: str) -> Done:
        return await self._clock_events(owners, now, on_watchdog)

    async def tick_beat(self, owners: Sequence[str], now: datetime, me: str) -> Done:
        return await self._clock_events(owners, now, on_tick)

    async def report_jobs(self, owners: Sequence[str], now: datetime, me: str) -> Done:
        """One `job_failing` naming every job in a streak (never `me`), once per streak, at most
        one an hour; `selfwatch_ok` once every told streak has ended."""
        told = 0
        if self.ledger.take_recovered():
            cause = f"jobs_back:{self.ledger.last_alert}"
            told += await self.teller.tell(owners, "selfwatch_ok", cause, texts.jobs_back(), now)
        failing = self.ledger.failing(self.streak, exclude=me)
        new = set(self.ledger.untold(self.streak, exclude=me))
        last = self.ledger.last_alert
        if not new or (last is not None and now - last < JOB_ALERT_EVERY):
            return told, True
        streaks = dict(failing)
        for subject, group in job_alerts([n for n, _ in failing]):
            fresh = [n for n in group if n in new]
            if not fresh:
                continue
            cause = ",".join(_streak_id(n, streaks[n]) for n in fresh)
            text = texts.job_failing(group)
            told += await self.teller.tell(owners, "job_failing", cause, text, now, subject=subject)
            self.ledger.mark_told(fresh, now)
        self.ledger.last_alert = now
        self.ledger.dirty = True
        return told, True

    async def errors_step(self, owners: Sequence[str], now: datetime, me: str) -> Done:
        """The counts written; each day just written with an hour over the limit is said once
        (a count from before midnight written after it still counts for its own day)."""
        try:
            written, kept = await self.errors.write_counts(self.docs), True
        except Exception as exc:  # noqa: BLE001 - the counts wait for the next run
            log.warning("selfwatch error counts not kept", extra={"error": type(exc).__name__})
            written, kept = self.errors.pending(), False
        if self.ledger.has_told():  # the jobs' own errors: the same incident, said once
            return 0, kept
        told = 0
        text = texts.errors_piling(self.errors_limit)
        for day, doc in sorted(written.items()):
            if errs.over(doc, self.errors_limit):
                told += await self.teller.tell(owners, "errors_piling", f"errors:{day}", text, now)
        return told, kept

    async def briefs_step(self, owners: Sequence[str], now: datetime, me: str) -> Done:
        told, kept = 0, True
        for uid in owners:
            try:
                got = await self.briefs.missed(uid, now)
            except Exception as exc:  # noqa: BLE001 - one owner's brief never stops the rest
                log.warning("selfwatch brief unreadable", extra={"error": type(exc).__name__})
                kept = False
                continue
            if got is not None:
                day, by = got
                text = texts.brief_missed(by)
                told += await self.teller.tell((uid,), "brief_missed", f"brief:{day}", text, now)
        return told, kept

    async def deploy_step(self, owners: Sequence[str], now: datetime, me: str) -> Done:
        got = await self.deploys.check(self.docs, now)
        if got is None:
            return 0, True
        cause, version = got
        text = texts.deploy_changed(version)
        return await self.teller.tell(owners, "deploy_changed", f"deploy:{cause}", text, now), True

    async def once_a_day(self, owners: Sequence[str], now: datetime, me: str) -> Done:
        """The first morning tick of the local day: the spend snapshot, then the sweeps."""
        day = now.astimezone(self.tz).date().isoformat()
        if self._day_done == day:
            return 0, True
        told = 0
        for uid, inr in (await self.spend.snapshot(self.docs, owners, now)).items():
            text = texts.spend_spike(inr, self.factor)
            told += await self.teller.tell((uid,), "spend_spike", f"spend:{day}", text, now)
        await self.told.sweep(now)
        await self.errors.sweep(self.docs, now)
        self._day_done = day
        return told, True


class _Job:
    """A `ticks.TickJob` running the watch's steps."""

    def __init__(self, name: str, budget_s: float, watch: Watch, steps: Sequence[Step]) -> None:
        self.name, self.budget_s = name, budget_s
        self._watch, self._steps = watch, tuple(steps)
        self.last: dict[str, int] = {}

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        self.last = await self._watch.run_steps(self.name, owners, self._steps)
        return self.last


__all__ = [
    "CLOCK_BUDGET_S",
    "CLOCK_NAME",
    "DAILY_BUDGET_S",
    "DAILY_NAME",
    "JOB_ALERT_EVERY",
    "Watch",
    "job_alerts",
]
