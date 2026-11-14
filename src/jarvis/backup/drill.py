# src/jarvis/backup/drill.py
"""The monthly restore drill (docs/plans/r14-hardening.md D4 "Drill", review A2, A3): a state
machine in `{prefix}backup_drill/current` (`backup.log`), one step per morning tick (job
`backup_drill`), so a slow restore or a long check simply carries on at the next tick.

- idle: due on `backup_drill_day` from 05:00 his time (a month whose day was missed runs at the
  next morning tick), or after he approved the `vitals_drill_start` card (`request`: at most
  `backup_drill_manual_per_month` a month; one drill at a time). Any drill that starts is the
  month's drill: the scheduled one doesn't follow it in the same month. Nothing is asked of Google
  before the set-up has been seen (no schedule ever seen: "not set up").
- start: the newest READY backup whose stats are FILLED with a document count over 0 (empty
  stats: "not yet", never start); refused (a "failed: over_cap" result, nothing restored) when
  its restore at the LIVE rate costs more than `backup_drill_max_inr`; refused without a key.
  A `jarvis-drill` database that is already there is cleaned up first and the restore waits
  for the next tick (an id is reusable 5 minutes after a delete).
- restoring: the operation is polled each tick; done without a database: "failed: restore".
- verifying: `verify.advance` within the tick's time; a check that raises 3 times in a row ends
  the drill ("failed: unknown").
- cleanup: `get_database("jarvis-drill")` decides, never the stored state alone; delete
  protection off first, then delete; the result was stored and told when the checks ended. It
  runs WHATEVER the switches say: when idle, once a day the job asks whether a copy is there.
  A copy that can't be deleted is told after 2 days, then weekly (`Teller`, "copy_left").
A run older than 3 days fails ("stuck"). Switched off mid-run: "skipped: switched off", no
alert. Every Google call goes through the admin adapter (`drill_target` first); the checks read
both sides through read-only views.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from jarvis.backup import verify
from jarvis.backup.log import DrillLog, DrillResult, DrillState, Outcome, Run, month_key
from jarvis.backup.ports import (
    DRILL_DB,
    BackupAdmin,
    BackupInfo,
    DatabaseInfo,
    DrillWalk,
    ReadOnlyDocs,
)
from jarvis.backup.status import BackupStatusService, Teller, restore_inr
from jarvis.config import Settings
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.ticks import time_left as tick_time_left
from jarvis.vitals.models import zone_of

log = get_logger(__name__)

STUCK = dt.timedelta(days=3)
REUSE_WAIT = dt.timedelta(minutes=6)  # Google: an id is reusable 5 minutes after a delete
LEFT_OVER = dt.timedelta(days=2)
AUTO_FROM_HOUR = 5
MAX_ERRORS = 3
REQUESTED = (
    "Done, Sir: the restore drill starts at JARVIS's next morning check, and its result shows "
    "in Vitals once it has finished, usually the same morning."
)
ALREADY = "A restore drill is already on its way, Sir; its result shows in Vitals when it ends."
NOT_SET_UP_LINE = (
    "Backups aren't set up yet, Sir, so there is nothing to test. Run the one-time step first: "
    "bash deploy/backup_setup.sh in Cloud Shell."
)
OFF_LINE = "The restore drill is switched off on this server, Sir."
CAP_LINE = (
    "You've had {n} restore drills this month already, Sir, which is the limit. The next one "
    "runs on its own on day {day} of next month."
)


class Walker(DrillWalk, ReadOnlyDocs, Protocol):
    """The drill copy's reader: its collections, counts and samples, and get / query."""


@dataclass(frozen=True)
class DrillDeps:
    s: Settings
    admin: BackupAdmin
    walk: Callable[[], Walker]
    live: ReadOnlyDocs
    log: DrillLog
    status: BackupStatusService
    teller: Teller
    ring: Keyring | None
    rate: Callable[[], Awaitable[float]]
    clock: Callable[[], dt.datetime]
    prefix: str = "jarvis_"
    time_left: verify.TimeLeft = tick_time_left
    keys: verify.Keys = field(default=verify.APP_KEYS)


def _newest_filled(backups: Sequence[BackupInfo]) -> BackupInfo | None:
    ready = [b for b in backups if b.stats_ready and b.snapshot_time is not None]
    return max(ready, key=lambda b: b.snapshot_time or dt.datetime.min) if ready else None


def _short_id(name: str) -> str:
    return name.rsplit("/", 1)[-1][:200]


class Drill:
    def __init__(self, deps: DrillDeps) -> None:
        self.d = deps

    def _on(self) -> bool:
        return self.d.s.backup_checks_enabled and self.d.s.backup_drill_enabled

    def _local(self, now: dt.datetime) -> dt.datetime:
        return now.astimezone(zone_of(self.d.s.user_timezone))

    def _due(self, st: DrillState, now: dt.datetime) -> bool:
        if not self._on():
            return False
        if st.requested_at is not None:
            return True
        local = self._local(now)
        return (
            local.day >= self.d.s.backup_drill_day
            and local.hour >= AUTO_FROM_HOUR
            and st.auto_month != month_key(local)
        )

    async def step(self, owners: Sequence[str]) -> str:
        """One tick's work; the word says what happened (for the job's counts)."""
        st = await self.d.log.state()
        if st.phase == "idle":
            return await self._idle(st, owners)
        if st.phase in ("restoring", "verifying") and st.run is not None:
            return await self._running(st, st.run, owners)
        return await self._cleanup(st, owners)

    # ---- idle and start ------------------------------------------------------------------------

    async def _idle(self, st: DrillState, owners: Sequence[str]) -> str:
        if not (await self.d.status.doc()).set_up:
            return "not_set_up"
        now = self.d.clock()
        if self._due(st, now):
            return await self._start(st, owners, now)
        today = self._local(now).strftime("%Y%m%d")
        if st.checked_on == today:
            return "idle"
        st = await self.d.log.save(st.model_copy(update={"checked_on": today}))
        try:
            found = await self.d.admin.get_database(DRILL_DB)  # a copy left over? (any switch)
        except PermissionError:  # access gone: the canary job tells him ("no_schedule")
            return "idle"
        if found is None:
            return "idle"
        st = st.model_copy(update={"phase": "cleanup", "copy_seen_at": st.copy_seen_at or now})
        return await self._cleanup(await self.d.log.save(st), owners, found)

    def _consumed(self, st: DrillState, now: dt.datetime) -> DrillState:
        """Any drill that starts (or is refused) is this month's: no second restore follows."""
        month = month_key(self._local(now))
        return st.model_copy(update={"requested_at": None, "auto_month": month})

    async def _refuse(self, st: DrillState, owners: Sequence[str], result: DrillResult) -> str:
        await self.d.log.record(result)
        await self.d.log.save(self._consumed(st, result.at))
        await self.d.teller.failed(owners, result.reason)
        return "refused"

    async def _start(self, st: DrillState, owners: Sequence[str], now: dt.datetime) -> str:
        manual = st.requested_at is not None
        if self.d.ring is None:
            return await self._refuse(
                st, owners, DrillResult(outcome="failed", reason="no_key", at=now, manual=manual)
            )
        try:
            pick = _newest_filled(await self.d.admin.list_backups())
        except PermissionError:
            return "not_set_up"
        if pick is None or pick.size_bytes is None or pick.document_count is None:
            return "waiting"  # Google hasn't filled the stats yet (A2): never start on those
        inr = restore_inr(pick.size_bytes, await self.d.rate())
        if inr > self.d.s.backup_drill_max_inr:
            refused = DrillResult(
                outcome="failed",
                reason="over_cap",
                at=now,
                manual=manual,
                backup=_short_id(pick.name),
                snapshot_time=pick.snapshot_time,
                expected=pick.document_count,
                inr=inr,
            )
            return await self._refuse(st, owners, refused)
        found = await self.d.admin.get_database(DRILL_DB)
        if found is not None:  # clean up first; the restore waits for the next tick
            st = st.model_copy(
                update={"phase": "cleanup", "run": None, "copy_seen_at": st.copy_seen_at or now}
            )
            return await self._cleanup(await self.d.log.save(st), owners, found)
        if st.deleted_at is not None and now - st.deleted_at < REUSE_WAIT:
            return "waiting"
        operation = await self.d.admin.restore(pick.name, DRILL_DB)
        run = Run(
            backup=pick.name,
            snapshot_time=pick.snapshot_time or now,
            expected=pick.document_count,
            size_bytes=pick.size_bytes,
            started_at=now,
            manual=manual,
            inr=inr,
            operation=operation,
        )
        await self.d.log.save(
            self._consumed(st, now).model_copy(update={"phase": "restoring", "run": run})
        )
        log.info("restore drill started", extra={"manual": manual, "documents": run.expected})
        return "started"

    # ---- restoring and verifying ---------------------------------------------------------------

    async def _running(self, st: DrillState, run: Run, owners: Sequence[str]) -> str:
        now = self.d.clock()
        if now - run.started_at > STUCK:
            return await self._end(st, run, owners, "failed", "stuck")
        if not self._on():
            return await self._end(st, run, owners, "skipped", "switched_off")
        if st.phase == "restoring":
            if not await self.d.admin.operation_done(run.operation or ""):
                run = run.model_copy(update={"polls": run.polls + 1})
                await self.d.log.save(st.model_copy(update={"run": run}))
                return "restoring"
            if await self.d.admin.get_database(DRILL_DB) is None:
                return await self._end(st, run, owners, "failed", "restore")
            st = await self.d.log.save(st.model_copy(update={"phase": "verifying"}))
        return await self._verifying(st, run, owners)

    async def _verifying(self, st: DrillState, run: Run, owners: Sequence[str]) -> str:
        if self.d.ring is None:
            return await self._end(st, run, owners, "failed", "no_key")
        walk = self.d.walk()
        job = verify.VerifyJob(
            walk=walk,
            drill=walk,
            live=self.d.live,
            ring=self.d.ring,
            prefix=self.d.prefix,
            snapshot=run.snapshot_time,
            expected=run.expected,
            owners=tuple(owners),
            keys=self.d.keys,
        )
        try:
            p = await verify.advance(
                verify.Progress.model_validate(run.progress), job, time_left=self.d.time_left
            )
        except Exception as exc:  # noqa: BLE001 - a check that raises is retried, then fails
            log.warning("restore drill check failed", extra={"error": type(exc).__name__})
            if run.errors + 1 >= MAX_ERRORS:
                return await self._end(st, run, owners, "failed", "unknown")
            run = run.model_copy(update={"errors": run.errors + 1})
            await self.d.log.save(st.model_copy(update={"run": run}))
            return "error"
        finally:
            await _close(walk)
        run = run.model_copy(update={"progress": p.model_dump(mode="json"), "errors": 0})
        st = st.model_copy(update={"run": run})
        if p.phase != "done":
            await self.d.log.save(st)
            return "verifying"
        outcome, reason = verify.outcome(p)
        return await self._end(st, run, owners, outcome, reason)

    # ---- the end, the clean-up -----------------------------------------------------------------

    def _result(self, run: Run, outcome: Outcome, reason: str | None) -> DrillResult:
        p = verify.Progress.model_validate(run.progress)
        now = self.d.clock()
        return DrillResult(
            outcome=outcome,
            reason=reason,
            at=now,
            manual=run.manual,
            backup=_short_id(run.backup),
            snapshot_time=run.snapshot_time,
            expected=run.expected,
            counted=p.counted,
            collections=p.collections,
            samples=p.samples,
            items=p.items,
            files=p.files,
            vault=p.vault,
            canary_ok=p.canary_ok,
            inr=run.inr,
            minutes=int((now - run.started_at).total_seconds() // 60),
        )

    async def _end(
        self,
        st: DrillState,
        run: Run,
        owners: Sequence[str],
        outcome: Outcome,
        reason: str | None,
    ) -> str:
        """Store and tell the result, then clean up (a failure still cleans up)."""
        result = self._result(run, outcome, reason)
        await self.d.log.record(result)
        run = run.model_copy(update={"result": result})
        st = await self.d.log.save(st.model_copy(update={"phase": "cleanup", "run": run}))
        if outcome == "passed":
            await self.d.teller.passed(owners)
        elif outcome == "failed":
            await self.d.teller.failed(owners, reason)
        log.info("restore drill ended", extra={"outcome": outcome, "reason": reason or ""})
        return await self._cleanup(st, owners)

    async def _delete(self, found: DatabaseInfo) -> bool:
        try:
            if found.delete_protection:
                await self.d.admin.set_delete_protection(DRILL_DB, False)
            await self.d.admin.delete_database(DRILL_DB)
        except Exception as exc:  # noqa: BLE001 - retried at the next tick; told after 2 days
            log.error("restore drill copy not deleted", extra={"error": type(exc).__name__})
            return False
        return True

    async def _cleanup(
        self, st: DrillState, owners: Sequence[str], found: DatabaseInfo | None = None
    ) -> str:
        now = self.d.clock()
        found = found or await self.d.admin.get_database(DRILL_DB)
        if found is not None:
            if await self._delete(found):
                st = st.model_copy(update={"deleted_at": now})
            found = await self.d.admin.get_database(DRILL_DB)
        if found is None:
            idle = {"phase": "idle", "run": None, "copy_seen_at": None}
            await self.d.log.save(st.model_copy(update=idle))
            return "done"
        seen = st.copy_seen_at or now
        await self.d.log.save(st.model_copy(update={"phase": "cleanup", "copy_seen_at": seen}))
        if now - seen > LEFT_OVER:
            await self.d.teller.problem(owners, "copy_left")
        return "cleaning"

    # ---- a drill he asked for (the card's run) -------------------------------------------------

    async def request(self) -> str:
        if not (await self.d.status.doc()).set_up:
            return NOT_SET_UP_LINE
        if not self._on():
            return OFF_LINE
        now = self.d.clock()
        month, cap = month_key(self._local(now)), self.d.s.backup_drill_manual_per_month

        def ask(st: DrillState) -> tuple[DrillState, str]:
            count = st.manual_count if st.manual_month == month else 0
            if st.requested_at is not None or st.phase != "idle":
                return st, ALREADY
            if count >= cap:
                return st, CAP_LINE.format(n=cap, day=self.d.s.backup_drill_day)
            asked = {"requested_at": now, "manual_month": month, "manual_count": count + 1}
            return st.model_copy(update=asked), REQUESTED

        return await self.d.log.change(ask)


async def _close(walk: object) -> None:
    close = getattr(walk, "close", None)
    if callable(close):
        try:
            await close()
        except Exception as exc:  # noqa: BLE001 - closing a reader never fails the drill
            log.warning("drill reader not closed", extra={"error": type(exc).__name__})


__all__ = [
    "ALREADY",
    "CAP_LINE",
    "NOT_SET_UP_LINE",
    "OFF_LINE",
    "REQUESTED",
    "Drill",
    "DrillDeps",
    "Walker",
]
