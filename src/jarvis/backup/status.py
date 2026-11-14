# src/jarvis/backup/status.py
"""The backups' facts and what he is told about them (docs/plans/r14-hardening.md D3-D5, data
model). Part A is the ONLY producer of `backup_problem`, `backup_ok` and the database-size item;
Part B and the Vitals board read the backups only through `BackupStatusService.facts()`
(`backup.ports.BackupStatus`, the service `backup_status`).

    {prefix}backup_status/current   schedule seen now, when it was FIRST seen (the set-up has run:
                                    only then may `backup_problem` begin, A6), the newest READY
                                    backup (id, snapshot time) and the newest with Google's stats
                                    filled (size, document count), how many copies, when each
                                    cause was last told

`refresh(admin)` lists the backups and the schedule (Firestore's admin API, free of charge);
before the owner's one-time step Google refuses (`PermissionError`) and the status stays "not set
up" with nothing told. The costs are in rupees at the live rate (S2 prices, read 14 Nov 2026).

`Teller`: alerts only through the app's notifier, fixed templates, no names, no amounts; the
claim is written BEFORE the send (a failed send is never sent again that day and never fails a
job); once per cause a day, the left-over drill copy weekly.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping, Sequence
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jarvis.backup.log import DrillLog
from jarvis.backup.ports import NOT_SET_UP, BackupAdmin, BackupFacts, BackupInfo
from jarvis.logging import get_logger
from jarvis.notify.ports import Notifier, Signal
from jarvis.storage.docs import Doc, Docs, DocTx, Set

log = get_logger(__name__)

STATUS_COLLECTION = "backup_status"
STATUS_ID = "current"
GIB: Final = 1024**3
BACKUP_USD_PER_GIB_HOUR: Final = 0.000041096  # S2: backup storage
RESTORE_USD_PER_GIB: Final = 0.20  # S2: a restore
STORED_USD_PER_GIB_HOUR: Final = 0.000205479  # S2: a named database's data (no free quota)
HOURS_PER_MONTH: Final = 730
RETENTION_DAYS: Final = 7  # the set-up's schedule: daily, kept 7 days
WEEKLY: Final = dt.timedelta(days=7) - dt.timedelta(hours=1)  # a tick may come a little early

TEXTS: Mapping[str, str] = {
    "stale": (
        "Backups: Google has made no new copy of your data for longer than expected. JARVIS "
        "checks again tomorrow; if it stays, send the Backups line in Vitals to the Workshop."
    ),
    "no_schedule": (
        "Backups: the daily backup schedule, or JARVIS's access to it, is gone, so no new copies "
        "are made. Run bash deploy/backup_setup.sh again in Cloud Shell."
    ),
    "key_changed": (
        "Backups: JARVIS's encryption key changed since yesterday, so older backups may not open "
        "with it. Send this to the Workshop today."
    ),
    "copy_left": (
        "Restore drill: its throw-away test copy could not be deleted, and Google charges for it "
        "while it stays. Send this to the Workshop."
    ),
    "drill_ok": (
        "Restore drill passed: the newest backup opened in a throw-away copy, everything was "
        "there, your locked documents opened, and the copy is deleted."
    ),
}
FAILED_TEXT = (
    "Restore drill failed: {why}. Your live data was not touched and JARVIS deletes the test "
    'copy. Say "test my backup" to try again; if it fails twice, send this to the Workshop.'
)
REASON_WORDS: Mapping[str, str] = {
    "count_mismatch": "the copy's document count did not match the backup",
    "canary_missing": "the daily check mark was missing from the copy",
    "canary_mismatch": "the daily check mark in the copy did not match",
    "key": "today's key could not open the copy",
    "vault_missing": "your vault was missing from the copy",
    "vault_mismatch": "a vault item in the copy differed",
    "vault_file": "a locked document in the copy did not open",
    "live_unreadable": "your live vault could not be read to compare",
    "sample_mismatch": "a document in the copy differed",
    "nothing_compared": "nothing could be compared",
    "restore": "Google could not make the copy",
    "over_cap": "the copy would cost more than the drill's limit",
    "stuck": "it took more than three days",
    "no_key": "this server has no encryption key",
    "unknown": "an unexpected error",
}


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def restore_inr(size_bytes: int, rate: float) -> float:
    """One restore of a backup this size, in rupees at `rate` (₹ per US dollar)."""
    return round(size_bytes / GIB * RESTORE_USD_PER_GIB * rate, 2)


def monthly_inr(size_bytes: int, rate: float, *, drills: int = 1) -> float:
    """7 daily copies kept plus `drills` restores a month, in rupees."""
    keep = RETENTION_DAYS * BACKUP_USD_PER_GIB_HOUR * HOURS_PER_MONTH
    return round(size_bytes / GIB * (keep + drills * RESTORE_USD_PER_GIB) * rate, 2)


def left_over_inr(size_bytes: int, rate: float) -> float:
    """A drill copy left standing for a month (stored data, no free quota), in rupees."""
    return round(size_bytes / GIB * STORED_USD_PER_GIB_HOUR * HOURS_PER_MONTH * rate, 2)


class StatusDoc(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    schedule_now: bool = False
    schedule_seen_at: dt.datetime | None = None
    checked_at: dt.datetime | None = None
    newest_name: str | None = Field(default=None, max_length=300)
    newest_at: dt.datetime | None = None
    size_bytes: int | None = None
    document_count: int | None = None
    copies: int = 0
    told: dict[str, dt.datetime] = Field(default_factory=dict)

    @property
    def set_up(self) -> bool:
        return self.schedule_seen_at is not None


def _doc_of(raw: Doc | None) -> StatusDoc:
    if raw is None:
        return StatusDoc()
    try:
        return StatusDoc.model_validate(raw)
    except ValidationError:
        log.error("backup status unreadable: read as not set up")
        return StatusDoc()


def _newest(backups: Sequence[BackupInfo]) -> tuple[BackupInfo | None, BackupInfo | None]:
    ready = sorted(
        (b for b in backups if b.state == "READY" and b.snapshot_time is not None),
        key=lambda b: b.snapshot_time or dt.datetime.min,
    )
    filled = [b for b in ready if b.stats_ready]
    return (ready[-1] if ready else None), (filled[-1] if filled else None)


def _due(last: dt.datetime | None, now: dt.datetime, weekly: bool, zone: dt.tzinfo) -> bool:
    """Weekly, or once a day on HIS day: UTC midnight (05:30 in Kolkata) is inside the tick."""
    if last is None:
        return True
    if weekly:
        return now - last >= WEEKLY
    return now.astimezone(zone).date() != last.astimezone(zone).date()


class BackupStatusService:
    """`backup.ports.BackupStatus`, the status writer and the claims."""

    def __init__(
        self,
        docs: Docs,
        drill_log: DrillLog,
        *,
        zone: dt.tzinfo,
        prefix: str = "jarvis_",
        clock: Callable[[], dt.datetime] = _now,
    ) -> None:
        self._d = docs
        self._zone = zone
        self._log = drill_log
        self._path = f"{prefix}{STATUS_COLLECTION}/{STATUS_ID}"
        self._clock = clock

    async def doc(self) -> StatusDoc:
        return _doc_of(await self._d.get(self._path))

    async def _save(self, doc: StatusDoc) -> StatusDoc:
        await self._d.write([Set(self._path, doc.model_dump(mode="json"))])
        return doc

    async def refresh(self, admin: BackupAdmin) -> StatusDoc:
        """List the backups and the schedule; before the set-up Google refuses: not set up."""
        now, doc = self._clock(), await self.doc()
        try:
            backups, schedules = list(await admin.list_backups()), list(await admin.schedules())
        except PermissionError:
            denied = {"schedule_now": False, "checked_at": now}
            return await self._save(doc.model_copy(update=denied))
        newest, filled = _newest(backups)
        seen = bool(schedules)
        update = {
            "schedule_now": seen,
            "schedule_seen_at": doc.schedule_seen_at or (now if seen else None),
            "checked_at": now,
            "newest_name": newest.name if newest else None,
            "newest_at": newest.snapshot_time if newest else None,
            "size_bytes": filled.size_bytes if filled else doc.size_bytes,
            "document_count": filled.document_count if filled else doc.document_count,
            "copies": sum(1 for b in backups if b.state == "READY"),
        }
        return await self._save(doc.model_copy(update=update))

    async def facts(self) -> BackupFacts:
        doc, last = await self.doc(), await self._log.last_result()
        if not doc.set_up and last is None:
            return NOT_SET_UP
        return BackupFacts(
            set_up=doc.set_up,
            schedule_seen_at=doc.schedule_seen_at,
            newest_at=doc.newest_at,
            size_bytes=doc.size_bytes,
            document_count=doc.document_count,
            drill=last.words if last is not None else None,
            drill_at=last.at if last is not None else None,
        )

    async def claim(self, cause: str, *, weekly: bool = False) -> bool:
        """Once per cause a day (weekly for the left-over copy), written before any send."""
        now = self._clock()

        async def run(tx: DocTx) -> bool:
            doc = _doc_of(await tx.get(self._path))
            if not _due(doc.told.get(cause), now, weekly, self._zone):
                return False
            told = {**doc.told, cause: now}
            tx.set(self._path, doc.model_copy(update={"told": told}).model_dump(mode="json"))
            return True

        return await self._d.transaction(run)


class Teller:
    """`backup_problem` / `backup_ok` through the app's notifier, fixed words only."""

    def __init__(self, status: BackupStatusService, notifier: Callable[[], Notifier | None]):
        self._status = status
        self._notifier = notifier

    async def problem(self, owners: Sequence[str], cause: str) -> int:
        weekly = cause == "copy_left"
        return await self._tell(owners, "backup_problem", cause, TEXTS[cause], weekly=weekly)

    async def failed(self, owners: Sequence[str], reason: str | None) -> int:
        why = REASON_WORDS.get(reason or "unknown", REASON_WORDS["unknown"])
        text = FAILED_TEXT.format(why=why)
        return await self._tell(owners, "backup_problem", "drill_failed", text)

    async def passed(self, owners: Sequence[str]) -> int:
        return await self._tell(owners, "backup_ok", "drill", TEXTS["drill_ok"], key="drill_ok")

    async def _tell(
        self,
        owners: Sequence[str],
        kind: str,
        subject: str,
        text: str,
        *,
        weekly: bool = False,
        key: str | None = None,
    ) -> int:
        notifier = self._notifier()
        if notifier is None or not owners:
            return 0
        if not await self._status.claim(key or subject, weekly=weekly):
            return 0
        sent = 0
        for uid in owners:
            try:
                signal = Signal(source="system", kind=kind, subject=subject)  # type: ignore[arg-type]
                await notifier.notify(uid, signal, text)
                sent += 1
            except Exception as exc:  # noqa: BLE001 - a failed send is no job failure
                log.warning("a backup alert was not sent", extra={"error": type(exc).__name__})
        return sent


__all__ = [
    "FAILED_TEXT",
    "GIB",
    "REASON_WORDS",
    "RETENTION_DAYS",
    "STATUS_COLLECTION",
    "TEXTS",
    "BackupStatusService",
    "StatusDoc",
    "Teller",
    "left_over_inr",
    "monthly_inr",
    "restore_inr",
]
