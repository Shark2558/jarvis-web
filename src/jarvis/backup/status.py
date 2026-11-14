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
claim is written BEFORE the send, once per cause on his day (the left-over drill copy weekly,
each drill's result once). A send that reached nobody (it raised, the storm's cap dropped it, or
no channel took it) gives its claim back, so a later tick tries again, at most `MAX_TRIES` times
on his day; it never fails a job. Where he chose it to go counts as told: a kind he switched
off, the home feed, a hold for the morning summary.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jarvis.alerts import AlertKind
from jarvis.backup.log import DrillLog
from jarvis.backup.ports import NOT_SET_UP, BackupAdmin, BackupFacts, BackupInfo
from jarvis.backup.texts import FAILED_TEXT, REASON_WORDS, TEXTS
from jarvis.logging import get_logger
from jarvis.notify.ports import Delivery, Notifier, Signal
from jarvis.storage.docs import Doc, Docs, DocTx

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
MAX_TRIES: Final = 3  # sends that reached nobody, per cause on his day
KEEP_ONCE: Final = dt.timedelta(days=40)  # a drill result's "told once" mark
DELIBERATE: Final = frozenset({"switched_off", "feed_only"})  # his choice, not a lost alert
KEY_CHANGE_TOLD: Final = dt.timedelta(days=RETENTION_DAYS)  # then every copy has the new key
Every = Literal["day", "week", "once"]


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


class Tries(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    day: str = Field(max_length=8)  # his day, yyyymmdd
    n: int = 0


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
    told: Mapping[str, dt.datetime] = Field(default_factory=dict)
    tries: Mapping[str, Tries] = Field(default_factory=dict)
    key_changed_at: dt.datetime | None = None  # told daily until a drill passes (or 7 days)

    @property
    def set_up(self) -> bool:
        return self.schedule_seen_at is not None

    def key_changing(self, now: dt.datetime) -> bool:
        at = self.key_changed_at
        return at is not None and now - at <= KEY_CHANGE_TOLD


def _doc_of(raw: Doc | None) -> StatusDoc:
    if raw is None:
        return StatusDoc()
    try:
        return StatusDoc.model_validate(raw)
    except ValidationError:
        log.error("backup status partly unreadable: its readable fields are kept")
        return _salvaged(raw)


def _salvaged(raw: Doc) -> StatusDoc:
    """Every field that reads on its own: one bad field never silences the alerts (set up)."""
    kept = {}
    for name in StatusDoc.model_fields:
        if name not in raw:
            continue
        try:
            StatusDoc.model_validate({name: raw[name]})
        except ValidationError:
            continue
        kept[name] = raw[name]
    return StatusDoc.model_validate(kept)


def _newest(backups: Sequence[BackupInfo]) -> tuple[BackupInfo | None, BackupInfo | None]:
    timed = [(b.snapshot_time, b) for b in backups if b.state == "READY" and b.snapshot_time]
    ready = [b for _, b in sorted(timed, key=lambda r: r[0])]  # aware times only, never mixed
    filled = [b for b in ready if b.stats_ready]
    return (ready[-1] if ready else None), (filled[-1] if filled else None)


def _due(last: dt.datetime | None, now: dt.datetime, every: Every, zone: dt.tzinfo) -> bool:
    """Once, weekly, or once a day on HIS day: UTC midnight (05:30 in Kolkata) is in the tick."""
    if last is None:
        return True
    if every == "once":
        return False
    if every == "week":
        return now - last >= WEEKLY
    return now.astimezone(zone).date() != last.astimezone(zone).date()


def _kept(told: Mapping[str, dt.datetime], now: dt.datetime) -> dict[str, dt.datetime]:
    """The told marks, without a drill result's once-mark past `KEEP_ONCE`."""
    return {k: v for k, v in told.items() if not (k.startswith("drill:") and now - v > KEEP_ONCE)}


@dataclass(frozen=True)
class Claim:
    """A cause claimed at `at`; `before` is the mark it replaced (given back on a lost send)."""

    cause: str
    at: dt.datetime
    before: dt.datetime | None


def reached(delivery: object) -> bool:
    """Did the alert reach him, or go where he chose (off, the feed, held for the morning)?"""
    if not isinstance(delivery, Delivery):
        return False
    if delivery.action == "hold":
        return True
    if delivery.action == "drop":
        return delivery.reason in DELIBERATE
    return delivery.telegram or delivery.push > 0


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

    async def _change(self, fold: Callable[[StatusDoc], StatusDoc]) -> StatusDoc:
        """Read-modify-write in one transaction: a claim made meanwhile is never erased."""

        async def run(tx: DocTx) -> StatusDoc:
            new = fold(_doc_of(await tx.get(self._path)))
            tx.set(self._path, new.model_dump(mode="json"))
            return new

        return await self._d.transaction(run)

    async def refresh(self, admin: BackupAdmin) -> StatusDoc:
        """List the backups and the schedule; before the set-up Google refuses: not set up."""
        now = self._clock()
        try:
            backups, schedules = list(await admin.list_backups()), list(await admin.schedules())
        except PermissionError:
            denied = {"schedule_now": False, "checked_at": now}
            return await self._change(lambda doc: doc.model_copy(update=denied))
        newest, filled = _newest(backups)
        seen, copies = bool(schedules), sum(1 for b in backups if b.state == "READY")

        def fold(doc: StatusDoc) -> StatusDoc:
            update = {
                "schedule_now": seen,
                "schedule_seen_at": doc.schedule_seen_at or (now if seen else None),
                "checked_at": now,
                "newest_name": newest.name if newest else None,
                "newest_at": newest.snapshot_time if newest else None,
                "size_bytes": filled.size_bytes if filled else doc.size_bytes,
                "document_count": filled.document_count if filled else doc.document_count,
                "copies": copies,
            }
            return doc.model_copy(update=update)

        return await self._change(fold)

    async def note_key_changed(self, now: dt.datetime) -> None:
        """The key changed (the canary job saw it): told daily until a drill passes."""
        await self._change(lambda doc: doc.model_copy(update={"key_changed_at": now}))

    async def clear_key_changed(self) -> None:
        """A restore drill passed with today's key: the key change is settled."""
        if (await self.doc()).key_changed_at is not None:
            await self._change(lambda doc: doc.model_copy(update={"key_changed_at": None}))

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

    def _day(self, at: dt.datetime) -> str:
        return at.astimezone(self._zone).strftime("%Y%m%d")

    async def claim(self, cause: str, *, every: Every = "day") -> Claim | None:
        """Written before any send; None when it is not due (or tried enough on his day)."""
        now = self._clock()
        day = self._day(now)

        async def run(tx: DocTx) -> Claim | None:
            doc = _doc_of(await tx.get(self._path))
            before, tried = doc.told.get(cause), doc.tries.get(cause)
            spent = tried is not None and tried.day == day and tried.n >= MAX_TRIES
            if spent or not _due(before, now, every, self._zone):
                return None
            told = {**_kept(doc.told, now), cause: now}
            tries = {k: v for k, v in doc.tries.items() if v.day == day}
            update = {"told": told, "tries": tries}
            tx.set(self._path, doc.model_copy(update=update).model_dump(mode="json"))
            return Claim(cause, now, before)

        return await self._d.transaction(run)

    async def release(self, claim: Claim) -> None:
        """The send reached nobody: the claim goes back and the try counts (`MAX_TRIES`)."""
        day = self._day(claim.at)

        async def run(tx: DocTx) -> None:
            doc = _doc_of(await tx.get(self._path))
            told = dict(doc.told)
            if told.get(claim.cause) == claim.at:  # still ours: give it back
                told.pop(claim.cause)
                if claim.before is not None:
                    told[claim.cause] = claim.before
            old = doc.tries.get(claim.cause)
            n = old.n + 1 if old is not None and old.day == day else 1
            tries = {**doc.tries, claim.cause: Tries(day=day, n=n)}
            update = {"told": told, "tries": tries}
            tx.set(self._path, doc.model_copy(update=update).model_dump(mode="json"))

        await self._d.transaction(run)


class Teller:
    """`backup_problem` / `backup_ok` through the app's notifier, fixed words only."""

    def __init__(self, status: BackupStatusService, notifier: Callable[[], Notifier | None]):
        self._status = status
        self._notifier = notifier

    async def problem(self, owners: Sequence[str], cause: str) -> int:
        every: Every = "week" if cause == "copy_left" else "day"
        return await self._tell(owners, "backup_problem", cause, TEXTS[cause], every=every)

    async def failed(self, owners: Sequence[str], reason: str | None, *, run: str) -> int:
        """One drill's failure, told once (`run` names the drill: two the same day are two)."""
        why = REASON_WORDS.get(reason or "unknown", REASON_WORDS["unknown"])
        text = FAILED_TEXT.format(why=why)
        return await self._tell(
            owners, "backup_problem", "drill_failed", text, every="once", key=f"drill:{run}"
        )

    async def passed(self, owners: Sequence[str], *, run: str) -> int:
        return await self._tell(
            owners, "backup_ok", "drill", TEXTS["drill_ok"], every="once", key=f"drill:{run}"
        )

    async def _tell(
        self,
        owners: Sequence[str],
        kind: AlertKind,
        subject: str,
        text: str,
        *,
        every: Every,
        key: str | None = None,
    ) -> int:
        """How many owners it reached; a send that reached nobody gives its claim back."""
        notifier = self._notifier()
        if notifier is None or not owners:
            return 0
        claim = await self._status.claim(key or subject, every=every)
        if claim is None:
            return 0
        signal = Signal(source="system", kind=kind, subject=subject)
        told = 0
        for uid in owners:
            told += await _send(notifier, uid, signal, text)
        if told == 0:
            log.error("a backup alert reached nobody: a later tick tries again",
                      extra={"subject": subject})  # fmt: skip
            await self._status.release(claim)
        return told


async def _send(notifier: Notifier, uid: str, signal: Signal, text: str) -> int:
    try:
        return int(reached(await notifier.notify(uid, signal, text)))
    except Exception as exc:  # noqa: BLE001 - a failed send is no job failure; tried again
        log.warning("a backup alert was not sent", extra={"error": type(exc).__name__})
        return 0


__all__ = [
    "FAILED_TEXT",
    "GIB",
    "MAX_TRIES",
    "REASON_WORDS",
    "RETENTION_DAYS",
    "STATUS_COLLECTION",
    "TEXTS",
    "BackupStatusService",
    "Claim",
    "StatusDoc",
    "Teller",
    "left_over_inr",
    "monthly_inr",
    "reached",
    "restore_inr",
]
