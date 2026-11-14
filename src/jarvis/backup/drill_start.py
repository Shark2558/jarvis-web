# src/jarvis/backup/drill_start.py
"""Starting the restore drill (docs/plans/r14-hardening.md D4 "start"; reviews A2, A3 and the R14
Part A review follow-ups).

- No key: refused ("no_key"), nothing restored.
- The newest READY backup whose stats are FILLED with a document count over 0 (empty stats:
  never start, A2). Its restore at the LIVE rate over `backup_drill_max_inr`: refused
  ("over_cap"), nothing restored.
- A `jarvis-drill` that is already there is cleaned up first; the restore waits at least
  `REUSE_WAIT` after a delete (Google: an id is reusable 5 minutes after it).
- Due but unable to start (no finished backup, or Google refuses: access lost): it waits, then
  after `BLOCKED_FOR` it is a failed result ("no_backup" / "no_access"), told, the month's drill,
  and a drill he asked for gives his monthly slot back.
- The INTENT is saved before `restore()` (the phase "restoring", the month consumed), so a tick
  cut off between the restore and its save can never restore twice: the next tick finds no
  operation and ends the drill ("interrupted"), whose clean-up deletes the copy. A restore Google
  refuses puts the state back as it was; one that fails otherwise may have begun, so the drill
  ends ("restore") and the clean-up decides.
Any drill that starts, or is refused, is the month's drill: no second restore follows it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import TYPE_CHECKING

from jarvis.backup.drill_deps import run_key, short_id
from jarvis.backup.drill_end import cleanup, end
from jarvis.backup.log import DrillResult, DrillState, Run
from jarvis.backup.ports import DRILL_DB, BackupInfo
from jarvis.backup.status import restore_inr
from jarvis.logging import get_logger

if TYPE_CHECKING:
    from jarvis.backup.drill_deps import DrillDeps

log = get_logger(__name__)

REUSE_WAIT = dt.timedelta(minutes=6)  # Google: an id is reusable 5 minutes after a delete
BLOCKED_FOR = dt.timedelta(days=2)


def newest_filled(backups: Sequence[BackupInfo]) -> BackupInfo | None:
    ready = [(b.snapshot_time, b) for b in backups if b.stats_ready and b.snapshot_time]
    return max(ready, key=lambda r: r[0])[1] if ready else None


def consumed(d: DrillDeps, st: DrillState, now: dt.datetime) -> DrillState:
    """Any drill that starts (or is refused) is this month's: no second restore follows."""
    month = {"requested_at": None, "auto_month": d.month(now), "blocked_since": None}
    return st.model_copy(update=month)


def refunded(d: DrillDeps, st: DrillState, now: dt.datetime) -> DrillState:
    """A drill he asked for that never ran: the request goes and his monthly slot comes back."""
    if st.requested_at is None:
        return st
    count = st.manual_count - 1 if st.manual_month == d.month(now) else st.manual_count
    return st.model_copy(update={"requested_at": None, "manual_count": max(0, count)})


async def refuse(d: DrillDeps, st: DrillState, owners: Sequence[str], result: DrillResult) -> str:
    await d.log.record(result)
    await d.log.save(consumed(d, st, result.at), request=True)
    await d.teller.failed(owners, result.reason, run=run_key(result.at))
    return "refused"


async def blocked(
    d: DrillDeps, st: DrillState, owners: Sequence[str], now: dt.datetime, reason: str
) -> str:
    """Due but unable to start: waits, then after `BLOCKED_FOR` a failed result, told."""
    since = st.blocked_since or now
    if now - since < BLOCKED_FOR:
        if st.blocked_since is None:
            await d.log.save(st.model_copy(update={"blocked_since": now}))
        return "waiting" if reason == "no_backup" else "no_access"
    manual = st.requested_at is not None
    result = DrillResult(outcome="failed", reason=reason, at=now, manual=manual)
    return await refuse(d, refunded(d, st, now), owners, result)


def _over_cap(pick: BackupInfo, inr: float, now: dt.datetime, manual: bool) -> DrillResult:
    return DrillResult(
        outcome="failed",
        reason="over_cap",
        at=now,
        manual=manual,
        backup=short_id(pick.name),
        snapshot_time=pick.snapshot_time,
        expected=pick.document_count,
        inr=inr,
    )


async def start(d: DrillDeps, st: DrillState, owners: Sequence[str], now: dt.datetime) -> str:
    manual = st.requested_at is not None
    if d.ring is None:
        no_key = DrillResult(outcome="failed", reason="no_key", at=now, manual=manual)
        return await refuse(d, st, owners, no_key)
    try:
        pick = newest_filled(await d.admin.list_backups())
        found = await d.admin.get_database(DRILL_DB) if pick is not None else None
    except PermissionError:
        return await blocked(d, st, owners, now, "no_access")
    if pick is None or pick.size_bytes is None or pick.document_count is None:
        return await blocked(d, st, owners, now, "no_backup")  # never on empty stats (A2)
    inr = restore_inr(pick.size_bytes, await d.rate())
    if inr > d.s.backup_drill_max_inr:
        return await refuse(d, st, owners, _over_cap(pick, inr, now, manual))
    if found is not None:  # clean up first; the restore waits for the next tick
        seen = {"phase": "cleanup", "run": None, "copy_seen_at": st.copy_seen_at or now}
        return await cleanup(d, await d.log.save(st.model_copy(update=seen)), owners, found)
    if st.deleted_at is not None and now - st.deleted_at < REUSE_WAIT:
        return "waiting"
    run = Run(backup=pick.name, snapshot_time=pick.snapshot_time or now,
              expected=pick.document_count, size_bytes=pick.size_bytes, started_at=now,
              manual=manual, inr=inr)  # fmt: skip
    return await _restore(d, st, owners, run)


async def _restore(d: DrillDeps, st: DrillState, owners: Sequence[str], run: Run) -> str:
    intent = consumed(d, st, run.started_at).model_copy(update={"phase": "restoring", "run": run})
    saved = await d.log.save(intent, request=True)  # the intent first: never restored twice
    try:
        operation = await d.admin.restore(run.backup, DRILL_DB)
    except PermissionError:
        await d.log.save(st, request=True)  # nothing was restored: back as it was
        return await blocked(d, st, owners, run.started_at, "no_access")
    except Exception as exc:  # noqa: BLE001 - it may have begun: the clean-up decides
        log.error("restore drill not started", extra={"error": type(exc).__name__})
        return await end(d, saved, run, owners, "failed", "restore")
    run = run.model_copy(update={"operation": operation})
    await d.log.save(saved.model_copy(update={"run": run}))
    log.info("restore drill started", extra={"manual": run.manual, "documents": run.expected})
    return "started"


__all__ = [
    "BLOCKED_FOR",
    "REUSE_WAIT",
    "blocked",
    "consumed",
    "newest_filled",
    "refunded",
    "refuse",
    "start",
]
