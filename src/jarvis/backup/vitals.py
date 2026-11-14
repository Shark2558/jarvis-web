# src/jarvis/backup/vitals.py
"""Part A's Vitals items (docs/plans/r14-hardening.md D3-D5; `hardening.ports.VITALS_IDS`):
ordinary automatic items through I0's slot (`vitals.own.OwnSources.r14`), so the console is
untouched. Fixed words, no Google call (they read the stored status and the drill's log).

- before his one-time step: ONLY `backups`, "not set up" (unknown, quiet: nothing rings and the
  brief does not nag), with the step and its cost range;
- `backups` (quiet): ok with the last copy, how long Google keeps it and the real monthly figure
  in rupees once the first copy's size is known; amber when the newest copy is older than
  `backup_max_age_h`; red when the schedule (or the access to it) is gone;
- `backup_drill` (quiet): unknown until the first drill, ok when it passed (amber "is overdue"
  once that pass is over 40 days old), red when it failed (its reason in fixed words; a count
  that didn't match shows both counts), amber when it was skipped for want of a vault, unknown
  when it was switched off, amber when the server has no token key (no canary, no drill);
- `db_size` (rings from Vitals: amber at the Vitals amber fraction, 80 %, red at 100 %): the
  newest backup's size against Firestore's free 1 GB, in MB.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Awaitable, Callable
from zoneinfo import ZoneInfo

from jarvis.backup.log import DrillLog, DrillResult
from jarvis.backup.status import REASON_WORDS, RETENTION_DAYS, BackupStatusService, StatusDoc
from jarvis.backup.tools import MIB, BackupDesk, day_words, overdue, when_words
from jarvis.billing.service import rupees
from jarvis.config import Settings
from jarvis.vitals.own import OwnItem, own_item

FREE_MB = 1024.0  # Firestore's free stored data: 1 GiB
NOT_SET_UP_NOTE = (
    "No copy of your data is kept yet. The one-time step turns backups on: bash "
    "deploy/backup_setup.sh in Cloud Shell (about ₹4 a month at 100 MB, about ₹40 at 1 GB)."
)
NO_SCHEDULE_NOTE = (
    "The daily backup schedule, or JARVIS's access to it, is gone: run bash "
    "deploy/backup_setup.sh again in Cloud Shell."
)
NO_COPY_NOTE = "Google makes the first copy within a day of the set-up; it shows here then."
SIZE_NOTE = "Measured from the newest backup; Firestore keeps 1 GB (1,024 MB) free."
NO_KEY_NOTE = (
    "This server has no token key, so JARVIS writes no daily check mark and can't run a restore "
    "drill. Send this to the Workshop."
)
OFF_NOTE = "Skipped on {on}: the restore drill is switched off on this server."
OVERDUE_NOTE = (
    'Last passed on {on}; the monthly drill hasn\'t run since. Say "test my backup", or send '
    "this to the Workshop if it stays."
)


def _backups(
    doc: StatusDoc, now: dt.datetime, tz: ZoneInfo, s: Settings, inr: float | None
) -> OwnItem:
    if not doc.schedule_now:
        return own_item("backups", "red", "has no daily schedule", note=NO_SCHEDULE_NOTE)
    since = doc.newest_at or doc.schedule_seen_at or now
    hours = s.backup_max_age_h
    if now - since > dt.timedelta(hours=hours):
        stale = f"has no copy newer than {hours} hours"
        return own_item("backups", "amber", stale, note="JARVIS tells you if it stays.")
    if doc.newest_at is None:
        return own_item("backups", "unknown", "has no copy yet", note=NO_COPY_NOTE)
    note = (
        f"Last copy {when_words(doc.newest_at, tz)}; Google keeps each copy {RETENTION_DAYS} days."
    )
    if inr is not None:
        note += f" About {rupees(inr)} a month at this size."
    return own_item("backups", "ok", "", note=note)


def _drill(last: DrillResult | None, now: dt.datetime, tz: ZoneInfo, desk: BackupDesk) -> OwnItem:
    if not desk.keyed:
        return own_item("backup_drill", "amber", "can't run: no token key", note=NO_KEY_NOTE)
    if last is None:
        first = f"The first drill runs on day {desk.s.backup_drill_day} of the month, or say "
        return own_item(
            "backup_drill", "unknown", "hasn't run yet", note=first + '"test my backup".'
        )
    on = day_words(last.at, tz, now)
    if overdue(last, now):
        return own_item("backup_drill", "amber", "is overdue", note=OVERDUE_NOTE.format(on=on))
    if last.outcome == "passed":
        note = (
            f"Passed on {on}: {last.counted or 0} documents counted, {last.items} vault items "
            f"and {last.samples} documents compared, the copy deleted."
        )
        return own_item("backup_drill", "ok", "", note=note)
    if last.outcome == "skipped" and last.reason == "switched_off":
        return own_item(
            "backup_drill", "unknown", "was skipped: switched off", note=OFF_NOTE.format(on=on)
        )
    if last.outcome == "skipped":
        note = f"Skipped on {on}: add a document to your vault so the next drill can open it."
        return own_item("backup_drill", "amber", "was skipped: no vault to open", note=note)
    why = REASON_WORDS.get(last.reason or "unknown", REASON_WORDS["unknown"])
    return own_item("backup_drill", "red", f"failed: {why}", note=_failed_note(last, on))


def _failed_note(last: DrillResult, on: str) -> str:
    if last.reason == "count_mismatch" and last.expected is not None:
        counted = f"{last.counted:,}" if last.counted is not None else "none"
        return (
            f"Failed on {on}: the backup said {last.expected:,} documents; the copy had {counted}."
        )
    return f"Failed on {on}."


def _size(doc: StatusDoc) -> list[OwnItem]:
    if not doc.size_bytes:
        return []
    used = round(doc.size_bytes / MIB, 1)
    return [
        own_item(
            "db_size", "ok", "", kind="storage", limit=FREE_MB, used=used, unit="MB", note=SIZE_NOTE
        )
    ]


def vitals_reader(
    desk: BackupDesk,
) -> Callable[[str, dt.datetime, ZoneInfo], Awaitable[list[OwnItem]]]:
    status: BackupStatusService = desk.status
    drill_log: DrillLog = desk.log

    async def read(uid: str, now: dt.datetime, tz: ZoneInfo) -> list[OwnItem]:
        doc = await status.doc()
        if not doc.set_up:
            return [own_item("backups", "unknown", "is not set up", note=NOT_SET_UP_NOTE)]
        last, inr = await drill_log.last_result(), await desk.month_inr(doc)
        return [_backups(doc, now, tz, desk.s, inr), _drill(last, now, tz, desk), *_size(doc)]

    return read


__all__ = ["FREE_MB", "NOT_SET_UP_NOTE", "vitals_reader"]
