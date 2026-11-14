# src/jarvis/backup/jobs.py
"""Part A's two morning-tick jobs (docs/plans/r14-hardening.md D4, D5; `hardening.ports`
`R14_JOB_NAMES`): no new Scheduler job, they ride the existing tick (`0,30 4-11`).

- `backup_canary` (while `backup_checks_enabled`): the day's canary, once (and the ones past 30
  days go), with a look at whether the key changed since the newest earlier canary; the status
  (backups and schedule, free admin calls) at most every `STATUS_EVERY`; then, ONLY once the
  set-up has been seen (a schedule seen once, A6), `backup_problem` once a cause a day: the
  newest READY copy older than `backup_max_age_h` ("stale"), the schedule gone ("no_schedule"),
  the key changed ("key_changed"). Before the set-up Google refuses: that is "not set up",
  never a job failure. Storage trouble is a failure (counted, so Part B can see a streak).
- `backup_drill`: one step of the restore drill (`drill.Drill.step`); a check that raised this
  tick is reported "failed" so a streak shows.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence

from jarvis.backup.canary import CanaryStore, day_key
from jarvis.backup.drill import Drill
from jarvis.backup.ports import BackupAdmin
from jarvis.backup.status import BackupStatusService, StatusDoc, Teller
from jarvis.config import Settings
from jarvis.keyring import Keyring
from jarvis.logging import get_logger

log = get_logger(__name__)

CANARY_JOB = "backup_canary"
DRILL_JOB = "backup_drill"
STATUS_EVERY = dt.timedelta(hours=3)


class BackupCanaryJob:
    name = CANARY_JOB
    budget_s = 30.0

    def __init__(
        self,
        *,
        s: Settings,
        canaries: CanaryStore,
        status: BackupStatusService,
        teller: Teller,
        admin: BackupAdmin | None,
        ring: Keyring | None,
        clock: Callable[[], dt.datetime],
    ) -> None:
        self._s, self._canaries, self._status = s, canaries, status
        self._teller, self._admin, self._ring, self._clock = teller, admin, ring, clock

    async def _canary(self, now: dt.datetime) -> tuple[int, bool]:
        """(1 when today's canary was written now, whether the key changed)."""
        if self._ring is None:
            return 0, False
        changed = await self._canaries.key_changed(self._ring, day_key(now))
        written = await self._canaries.write(self._ring, now)
        await self._canaries.prune(now)
        return int(written), changed

    async def _refreshed(self, now: dt.datetime) -> tuple[StatusDoc, int]:
        doc = await self._status.doc()
        due = doc.checked_at is None or now - doc.checked_at >= STATUS_EVERY
        if self._admin is None or not due:
            return doc, 0
        return await self._status.refresh(self._admin), 1

    async def _tell(
        self, owners: Sequence[str], doc: StatusDoc, now: dt.datetime, changed: bool
    ) -> int:
        if not doc.set_up:
            return 0  # nothing about backups before his one-time step (A6)
        told = 0
        if changed:
            told += await self._teller.problem(owners, "key_changed")
        if not doc.schedule_now:
            told += await self._teller.problem(owners, "no_schedule")
        since = doc.newest_at or doc.schedule_seen_at
        if since is not None and now - since > dt.timedelta(hours=self._s.backup_max_age_h):
            told += await self._teller.problem(owners, "stale")
        return told

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        counts = {"canary": 0, "listed": 0, "told": 0, "failed": 0}
        if not self._s.backup_checks_enabled:
            return counts
        now, changed = self._clock(), False
        try:
            counts["canary"], changed = await self._canary(now)
            doc, counts["listed"] = await self._refreshed(now)
        except Exception as exc:  # noqa: BLE001 - counted: the tick reports the job failed
            log.error("backup checks failed", extra={"error": type(exc).__name__})
            counts["failed"] += 1
            return counts
        counts["told"] = await self._tell(owners, doc, now, changed)
        return counts


class BackupDrillJob:
    name = DRILL_JOB
    budget_s = 60.0

    def __init__(self, drill: Drill | None) -> None:
        self._drill = drill

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        if self._drill is None:
            return {"off": 1}
        word = await self._drill.step(owners)
        return {word: 1, "failed": 1 if word == "error" else 0}


__all__ = ["CANARY_JOB", "DRILL_JOB", "STATUS_EVERY", "BackupCanaryJob", "BackupDrillJob"]
