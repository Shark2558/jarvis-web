# src/jarvis/backup/drill_end.py
"""The restore drill's end and its clean-up (docs/plans/r14-hardening.md D4 "cleanup"; reviews
A2, A3 and the R14 Part A review follow-ups).

- `end`: the result is stored (`DrillLog.record`) and told once, under the drill's own run key
  (passed -> `backup_ok`, and a key change is settled; failed -> `backup_problem` "drill_failed"
  with its reason in fixed words; skipped -> nothing), then the copy is cleaned up.
- `cleanup`: `get_database("jarvis-drill")` decides, never the stored state alone; delete
  protection off first, then delete, then look again. A look that fails (access lost, Google
  down) keeps the phase at clean-up like a copy that would not go: the copy may be there, so
  when it was first seen is stamped and after `LEFT_OVER` he is told ("copy_left"), then
  weekly. It never raises: the word says what happened (`no_access`, `error`, `cleaning`,
  `done`).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import TYPE_CHECKING

from jarvis.backup import verify
from jarvis.backup.drill_deps import run_key, short_id
from jarvis.backup.log import DrillResult, DrillState, Outcome, Run
from jarvis.backup.ports import DRILL_DB, DatabaseInfo
from jarvis.logging import get_logger

if TYPE_CHECKING:
    from jarvis.backup.drill_deps import DrillDeps

log = get_logger(__name__)

LEFT_OVER = dt.timedelta(days=2)


def result_of(d: DrillDeps, run: Run, outcome: Outcome, reason: str | None) -> DrillResult:
    p = verify.Progress.model_validate(run.progress)
    now = d.clock()
    return DrillResult(
        outcome=outcome,
        reason=reason,
        at=now,
        manual=run.manual,
        backup=short_id(run.backup),
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


async def end(
    d: DrillDeps,
    st: DrillState,
    run: Run,
    owners: Sequence[str],
    outcome: Outcome,
    reason: str | None,
) -> str:
    """Store and tell the result, then clean up (a failure still cleans up)."""
    result = result_of(d, run, outcome, reason)
    await d.log.record(result)
    run = run.model_copy(update={"result": result})
    st = await d.log.save(st.model_copy(update={"phase": "cleanup", "run": run}))
    key = run_key(run.started_at)
    if outcome == "passed":
        await d.status.clear_key_changed()
        await d.teller.passed(owners, run=key)
    elif outcome == "failed":
        await d.teller.failed(owners, reason, run=key)
    log.info("restore drill ended", extra={"outcome": outcome, "reason": reason or ""})
    return await cleanup(d, st, owners)


async def _delete(d: DrillDeps, found: DatabaseInfo) -> bool:
    try:
        if found.delete_protection:
            await d.admin.set_delete_protection(DRILL_DB, False)
        await d.admin.delete_database(DRILL_DB)
    except Exception as exc:  # noqa: BLE001 - retried at the next tick; told after 2 days
        log.error("restore drill copy not deleted", extra={"error": type(exc).__name__})
        return False
    return True


async def cleanup(
    d: DrillDeps, st: DrillState, owners: Sequence[str], found: DatabaseInfo | None = None
) -> str:
    now = d.clock()
    try:
        found = found or await d.admin.get_database(DRILL_DB)
        if found is not None:
            if await _delete(d, found):
                st = st.model_copy(update={"deleted_at": now})
            found = await d.admin.get_database(DRILL_DB)
    except Exception as exc:  # noqa: BLE001 - the copy may be there: kept as left over
        log.warning("restore drill copy not looked at", extra={"error": type(exc).__name__})
        word = "no_access" if isinstance(exc, PermissionError) else "error"
        return await _left(d, st, owners, now, word)
    if found is None:
        idle = {"phase": "idle", "run": None, "copy_seen_at": None}
        await d.log.save(st.model_copy(update=idle))
        return "done"
    return await _left(d, st, owners, now, "cleaning")


async def _left(
    d: DrillDeps, st: DrillState, owners: Sequence[str], now: dt.datetime, word: str
) -> str:
    seen = st.copy_seen_at or now
    await d.log.save(st.model_copy(update={"phase": "cleanup", "copy_seen_at": seen}))
    if now - seen > LEFT_OVER:
        await d.teller.problem(owners, "copy_left")
    return word


__all__ = ["LEFT_OVER", "cleanup", "end", "result_of"]
