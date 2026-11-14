# src/jarvis/selfwatch/jobs.py
"""Part B's watch and its two jobs (docs/plans/r14-hardening.md D5, D7, review A6).

`Watch` holds what the self-health watch knows (the job ledger, the clocks, the errors handler,
the once-only claims) and the tick observer (`observe`, synchronous, never raises). Its jobs:

- `selfwatch_clock` (5 minutes, advisory, FIRST on both 5-minute paths, for the brief's owners):
  the 5-minute clock's stamp and the morning clock's check, the error counts written, the job
  streaks, the errors, the brief, a new version.
- `selfwatch_daily` (the morning tick, after the other jobs): the morning clock's stamp and the
  5-minute clock's check, the job streaks, and once a day the spend snapshot and the sweeps.

Each step stands alone and has a fair share of the time left (`ticks.time_left()`, else the
job's budget): what is left before `STEPS_SHARE` of it, split over the steps still to run, so
one that hangs is cut and the rest still run; the ledger is then written in the slice kept for
it (`FLUSH_SHARE`), in a `finally`, even when the tick cuts the job from outside.
One that fails or is cut is logged as a class name and counted under `failed`
(the job's own streak, which the OTHER job reports: a selfwatch job never reports itself), and
the rest still run. Job failures go out as ONE `job_failing` naming every job in a streak, at
most one an hour per owner (`JOB_ALERT_EVERY`), each streak once; errors piling up are held
while a streak told in the last `ERRORS_HELD` (6 hours) is still going: those hours are that
incident's, said once (`errors.Piles`); any other hour over the limit is said, even later.

What an alert settles (a streak told, the hour's alert, an outage, a revision seen, a day's
spend or brief done) is committed only when the teller says it is settled (`texts.Said`): one
that reached nobody is raised again by the next run.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from jarvis.config import Settings
from jarvis.logging import get_logger
from jarvis.notify.ports import Notifier
from jarvis.selfwatch import errors as errs
from jarvis.selfwatch import texts
from jarvis.selfwatch.brief_check import BriefCheck, BriefLike
from jarvis.selfwatch.clocks import Clocks, ClockState, Event, on_tick, on_watchdog, undo
from jarvis.selfwatch.deploys import DeployWatch
from jarvis.selfwatch.errors import ErrorCounter
from jarvis.selfwatch.ledger import JobLedger, Streak, Told
from jarvis.selfwatch.spend import BillingLike, SpendWatch
from jarvis.storage.docs import Docs
from jarvis.ticks import FAILED_COUNT, JobOutcome, time_left
from jarvis.undo.store import owner_ok

log = get_logger(__name__)

CLOCK_NAME = "selfwatch_clock"
DAILY_NAME = "selfwatch_daily"
CLOCK_BUDGET_S = 10.0  # it runs first in the watchdog's 50 s (a healthy run takes milliseconds)
DAILY_BUDGET_S = 25.0
JOB_ALERT_EVERY = timedelta(hours=1)  # A6: one aggregated `job_failing` an hour per owner
ERRORS_HELD = timedelta(hours=6)  # errors wait this long after a job alert, not all its streak
STEPS_SHARE = 0.85  # of the job's time, for its steps
FLUSH_SHARE = 0.10  # for writing the ledger (the rest is spare)
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
        self.piles = errs.Piles()
        self.told = Told(docs, prefix=p)
        self.teller = texts.Teller(notifier, self.told)
        grace = timedelta(minutes=s.selfwatch_brief_grace_min)
        self.briefs = BriefCheck(brief, grace=grace, tz=self.tz)
        self.spend = SpendWatch(
            billing, tz=self.tz, factor=self.factor, min_inr=s.selfwatch_spike_min_inr, prefix=p
        )
        self.deploys = DeployWatch(revision=s.cloud_run_revision, version=version, prefix=p)
        self._day_done: str | None = None
        self.clock_job = Job(CLOCK_NAME, CLOCK_BUDGET_S, self, self._clock_steps())
        self.daily_job = Job(DAILY_NAME, DAILY_BUDGET_S, self, self._daily_steps())

    def _clock_steps(self) -> tuple[Step, ...]:
        return (
            self.load,
            self.watchdog_beat,
            self.report_jobs,  # an incident's job alert first: its errors are then held
            self.briefs_step,  # before the errors: never the one a slow write starves
            self.errors_step,
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
        self, me: str, owners: Sequence[str], steps: Sequence[Step], budget_s: float
    ) -> dict[str, int]:
        now = self.now()
        owners = tuple(u for u in owners if isinstance(u, str) and owner_ok(u))
        counts = {"owners": len(owners), "told": 0, FAILED_COUNT: 0}
        clock = asyncio.get_running_loop().time
        left = time_left()
        total = budget_s if left is None else max(0.0, min(left, budget_s))
        end = clock() + total * STEPS_SHARE
        try:
            for i, step in enumerate(steps):
                share = (end - clock()) / (len(steps) - i)
                told, kept = await self._step(step, owners, now, me, share)
                counts["told"] += told
                counts[FAILED_COUNT] += int(not kept)
        finally:  # also when the tick cuts the job from outside
            counts[FAILED_COUNT] += int(not await self._flush(total * FLUSH_SHARE))
        return counts

    async def _step(
        self, step: Step, owners: Sequence[str], now: datetime, me: str, share: float
    ) -> Done:
        extra = {"job": me, "step": getattr(step, "__name__", "step")}
        if share <= 0:
            log.warning("selfwatch step cut: no time left", extra=extra)
            return 0, False
        try:
            async with asyncio.timeout(share):
                return await step(owners, now, me)
        except TimeoutError:
            log.warning("selfwatch step cut at its share of the time", extra=extra)
        except Exception as exc:  # noqa: BLE001 - one step never stops the others
            log.warning("selfwatch step failed", extra={**extra, "error": type(exc).__name__})
        return 0, False

    async def _flush(self, limit_s: float) -> bool:
        try:
            async with asyncio.timeout(max(limit_s, 0.05)):
                await self.ledger.flush(self.docs)
        except Exception as exc:  # noqa: BLE001 - kept dirty for the next run
            log.warning("selfwatch ledger not kept", extra={"error": type(exc).__name__})
            return False
        return True

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
        told, owed = 0, []
        for e in events:
            said = await self.teller.tell(owners, e.kind, e.cause, _text(e), now, subject=e.clock)
            told += said.sent
            if not said.settled:
                owed.append(e)
        if owed:  # reached nobody: as if it had not happened, so the next run raises it again

            def back(s: ClockState) -> ClockState:
                for e in owed:
                    s = undo(s, e)
                return s

            kept = (await self.clocks.update(self.docs, back))[1] and kept
        return told, kept

    async def watchdog_beat(self, owners: Sequence[str], now: datetime, me: str) -> Done:
        return await self._clock_events(owners, now, on_watchdog)

    async def tick_beat(self, owners: Sequence[str], now: datetime, me: str) -> Done:
        return await self._clock_events(owners, now, on_tick)

    async def report_jobs(self, owners: Sequence[str], now: datetime, me: str) -> Done:
        """One `job_failing` naming every job in a streak (never `me`), once per streak, at most
        one an hour; `selfwatch_ok` once every told streak has ended."""
        told = 0
        if self.ledger.recovered():
            cause = f"jobs_back:{self.ledger.last_alert}"
            said = await self.teller.tell(owners, "selfwatch_ok", cause, texts.jobs_back(), now)
            told += said.sent
            if said.settled:
                self.ledger.clear_recovered()
        failing = self.ledger.failing(self.streak, exclude=me)
        new = set(self.ledger.untold(self.streak, exclude=me))
        last = self.ledger.last_alert
        if not new or (last is not None and now - last < JOB_ALERT_EVERY):
            return told, True
        streaks, settled = dict(failing), True
        for subject, group in job_alerts([n for n, _ in failing]):
            fresh = [n for n in group if n in new]
            if not fresh:
                continue
            cause = ",".join(_streak_id(n, streaks[n]) for n in fresh)
            text = texts.job_failing(group)
            said = await self.teller.tell(owners, "job_failing", cause, text, now, subject=subject)
            told += said.sent
            if said.settled:
                self.ledger.mark_told(fresh, now)
            settled = settled and said.settled
        if settled:  # the hour's alert is used only by one that was said
            self.ledger.last_alert = now
            self.ledger.dirty = True
        return told, True

    async def errors_step(self, owners: Sequence[str], now: datetime, me: str) -> Done:
        """The counts written; each day with an hour over the limit is said once, until its
        alert is settled (a count from before midnight written after it counts for its day)."""
        try:
            written, kept = await self.errors.write_counts(self.docs), True
        except Exception as exc:  # noqa: BLE001 - the counts wait for the next run
            log.warning("selfwatch error counts not kept", extra={"error": type(exc).__name__})
            written, kept = self.errors.pending(), False
        lost = self.errors.new_unrecorded()
        if lost:
            log.warning("selfwatch errors handler could not count records", extra={"count": lost})
        held = self.ledger.has_told(since=now - ERRORS_HELD)  # the same incident, said once
        self.piles.see(written, self.errors_limit, held=held)
        told, text = 0, texts.errors_piling(self.errors_limit)
        for day in [] if held else self.piles.owed():
            said = await self.teller.tell(owners, "errors_piling", f"errors:{day}", text, now)
            told += said.sent
            if said.settled:
                self.piles.settle(day)
        return told, kept and not lost

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
                said = await self.teller.tell((uid,), "brief_missed", f"brief:{day}", text, now)
                told += said.sent
                if said.settled:
                    self.briefs.settle(uid)
        return told, kept

    async def deploy_step(self, owners: Sequence[str], now: datetime, me: str) -> Done:
        got = await self.deploys.check(self.docs, now)
        if got is None:
            return 0, True
        cause, version = got
        text = texts.deploy_changed(version)
        said = await self.teller.tell(owners, "deploy_changed", f"deploy:{cause}", text, now)
        if said.settled:
            await self.deploys.remember(self.docs, now)
        return said.sent, True

    async def once_a_day(self, owners: Sequence[str], now: datetime, me: str) -> Done:
        """Each owner's spend snapshot until his day is done (a failure is tried at the next
        tick), then the first morning tick of the local day sweeps."""
        day = self.spend.day_of(now)
        snap = await self.spend.snapshot(self.docs, owners, now)
        told = 0
        for uid, inr in snap.spikes.items():
            text = texts.spend_spike(inr, self.factor)
            said = await self.teller.tell((uid,), "spend_spike", f"spend:{day}", text, now)
            told += said.sent
            if said.settled:
                self.spend.settle(uid, day)
        if self._day_done != day:
            await self.told.sweep(now)
            await self.errors.sweep(self.docs, now)
            self._day_done = day
        return told, not snap.failed


def _text(e: Event) -> str:
    if e.kind == "clock_stopped":
        return texts.clock_stopped(e.clock, e.at, never=e.never)
    return texts.clock_back(e.clock)


class Job:
    """A `ticks.TickJob` running the watch's steps."""

    def __init__(self, name: str, budget_s: float, watch: Watch, steps: Sequence[Step]) -> None:
        self.name, self.budget_s = name, budget_s
        self._watch, self._steps = watch, tuple(steps)
        self.last: dict[str, int] = {}

    @property
    def step_names(self) -> list[str]:
        return [getattr(step, "__name__", "step") for step in self._steps]

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        self.last = await self._watch.run_steps(self.name, owners, self._steps, self.budget_s)
        return self.last


__all__ = [
    "CLOCK_BUDGET_S",
    "FLUSH_SHARE",
    "STEPS_SHARE",
    "CLOCK_NAME",
    "DAILY_BUDGET_S",
    "DAILY_NAME",
    "ERRORS_HELD",
    "JOB_ALERT_EVERY",
    "Job",
    "Watch",
    "job_alerts",
]
