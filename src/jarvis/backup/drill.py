# src/jarvis/backup/drill.py
"""The monthly restore drill (docs/plans/r14-hardening.md D4 "Drill", review A2, A3): a state
machine in `{prefix}backup_drill/current` (`backup.log`), one step per morning tick (job
`backup_drill`), so a slow restore or a long check simply carries on at the next tick. Its start
is `drill_start`, its end and clean-up `drill_end`, what they share `drill_deps`.

- idle: due on `backup_drill_day` from 05:00 his time (a month whose day was missed runs at the
  next morning tick), or after he approved the `vitals_drill_start` card (`request`: at most
  `backup_drill_manual_per_month` a month; one drill at a time). Any drill that starts, or is
  refused, is the month's drill. Nothing is asked of Google before the set-up has been seen
  (no schedule ever seen: "not set up"). A request approved before the drill was switched off
  is dropped (a new approval is needed) and his slot comes back. Once a day, whatever the
  switches say, it asks whether a copy is left over; a refusal there is told ("no_access").
- start (`drill_start`): see there; due but unable to start for 2 days is a failed result.
- restoring: the operation is polled each tick; done without a database: "failed: restore";
  no operation saved (the tick was cut off after the restore began): "failed: interrupted".
- verifying: `verify.advance` within the tick's time; a check that raises 3 times in a row ends
  the drill ("failed: unknown").
- Google refusing any call mid-drill ends it ("failed: no_access"); the clean-up keeps trying.
- cleanup (`drill_end`): `get_database("jarvis-drill")` decides; a copy that can't be deleted
  (or looked at) is told after 2 days, then weekly ("copy_left").
A run older than 3 days fails ("stuck"). Switched off mid-run: "skipped: switched off", no
alert. Every Google call goes through the admin adapter (`drill_target` first); the checks read
both sides through read-only views.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

from jarvis.backup import verify
from jarvis.backup.drill_deps import DrillDeps, Walker
from jarvis.backup.drill_end import cleanup, end
from jarvis.backup.drill_start import refunded, start
from jarvis.backup.log import DrillState, Run, month_key
from jarvis.backup.ports import DRILL_DB
from jarvis.logging import get_logger

log = get_logger(__name__)

STUCK = dt.timedelta(days=3)
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


class Drill:
    def __init__(self, deps: DrillDeps) -> None:
        self.d = deps

    def _due(self, st: DrillState, now: dt.datetime) -> bool:
        if not self.d.on():
            return False
        if st.requested_at is not None:
            return True
        local = self.d.local(now)
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
        return await cleanup(self.d, st, owners)

    # ---- idle ----------------------------------------------------------------------------------

    async def _idle(self, st: DrillState, owners: Sequence[str]) -> str:
        if not (await self.d.status.doc()).set_up:
            return "not_set_up"
        now = self.d.clock()
        if st.requested_at is not None and not self.d.on():
            await self.d.log.save(refunded(self.d, st, now), request=True)
            log.info("a requested restore drill was dropped: switched off")
            return "off"
        if self._due(st, now):
            return await start(self.d, st, owners, now)
        today = self.d.local(now).strftime("%Y%m%d")
        if st.checked_on == today:
            return "idle"
        try:
            found = await self.d.admin.get_database(DRILL_DB)  # a copy left over? (any switch)
        except PermissionError:  # it can't look for (or delete) its copy: told, looked again
            log.warning("restore drill: no access to its copy")
            await self.d.teller.problem(owners, "no_access")
            return "no_access"
        st = await self.d.log.save(st.model_copy(update={"checked_on": today}))  # after the look
        if found is None:
            return "idle"
        st = st.model_copy(update={"phase": "cleanup", "copy_seen_at": st.copy_seen_at or now})
        return await cleanup(self.d, await self.d.log.save(st), owners, found)

    # ---- restoring and verifying ---------------------------------------------------------------

    async def _running(self, st: DrillState, run: Run, owners: Sequence[str]) -> str:
        now = self.d.clock()
        if now - run.started_at > STUCK:
            return await end(self.d, st, run, owners, "failed", "stuck")
        if not self.d.on():
            return await end(self.d, st, run, owners, "skipped", "switched_off")
        if st.phase == "restoring":
            if run.operation is None:  # the tick was cut off after the restore began
                return await end(self.d, st, run, owners, "failed", "interrupted")
            try:
                done = await self.d.admin.operation_done(run.operation)
                made = await self.d.admin.get_database(DRILL_DB) if done else None
            except PermissionError:
                return await end(self.d, st, run, owners, "failed", "no_access")
            if not done:
                run = run.model_copy(update={"polls": run.polls + 1})
                await self.d.log.save(st.model_copy(update={"run": run}))
                return "restoring"
            if made is None:
                return await end(self.d, st, run, owners, "failed", "restore")
            st = await self.d.log.save(st.model_copy(update={"phase": "verifying"}))
        return await self._verifying(st, run, owners)

    async def _verifying(self, st: DrillState, run: Run, owners: Sequence[str]) -> str:
        if self.d.ring is None:
            return await end(self.d, st, run, owners, "failed", "no_key")
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
        except PermissionError:
            return await end(self.d, st, run, owners, "failed", "no_access")
        except Exception as exc:  # noqa: BLE001 - a check that raises is retried, then fails
            log.warning("restore drill check failed", extra={"error": type(exc).__name__})
            if run.errors + 1 >= MAX_ERRORS:
                return await end(self.d, st, run, owners, "failed", "unknown")
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
        return await end(self.d, st, run, owners, outcome, reason)

    # ---- a drill he asked for (the card's run) -------------------------------------------------

    async def request(self) -> str:
        if not (await self.d.status.doc()).set_up:
            return NOT_SET_UP_LINE
        if not self.d.on():
            return OFF_LINE
        now = self.d.clock()
        month, cap = self.d.month(now), self.d.s.backup_drill_manual_per_month

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
