# src/jarvis/watch/jobs.py
"""Part D's background jobs (docs/plans/r7-mobile.md D17, D25; I0 seam 20). No model, no value in
a log line: counts only.

- `WatchStale` (the helpers' 5-minute clock, `watch_stale`): when a phone that once synced has
  been silent for `STALE_AFTER` (26 hours: the app syncs every 6 hours and when opened), the owner
  is told ONCE (an `info` alert, silent), until the next sync. Never for a phone that never synced.
- `BodySweep` (the morning tick, `body_sweep`): watch days older than `watch_keep_days` (400),
  SOS log entries older than 400 days and join words that ran out.
Each owner is served on his own: one owner's failure is counted (`failed`) and stops no one.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

from jarvis.logging import get_logger
from jarvis.notify.ports import Notifier, Signal
from jarvis.sos.store import SosStore
from jarvis.ticks import FAILED_COUNT
from jarvis.watch.service import WatchService

log = get_logger(__name__)
STALE_AFTER = timedelta(hours=26)
SOS_LOG_DAYS = 400
STALE_JOB, SWEEP_JOB = "watch_stale", "body_sweep"


def stale_words(local: datetime) -> str:
    return (
        f"Your phone hasn't sent your watch data since {local.day} {local.strftime('%b')}, "
        f"{local.strftime('%H:%M')}, Sir. Open the JARVIS app on your phone to sync."
    )


class WatchStale:
    name = STALE_JOB
    budget_s = 10.0

    def __init__(
        self,
        watch: WatchService,
        *,
        notifier: Callable[[], Notifier | None] | None,
        now: Callable[[], datetime],
    ) -> None:
        self._watch = watch
        self._notifier = notifier
        self._now = now

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        told = failed = 0
        if not self._watch.enabled or not self._watch.sealed:
            return {"told": 0}
        now = self._now()
        for uid in owners:
            try:
                told += await self._one(uid, now)
            except Exception as exc:  # noqa: BLE001 - one owner never stops another
                log.warning("watch_stale failed for an owner", extra={"error": type(exc).__name__})
                failed += 1
        return {"told": told, FAILED_COUNT: failed}

    async def _one(self, uid: str, now: datetime) -> int:
        state = await self._watch.state(uid)
        last = state.last_sync
        if last is None or now - last < STALE_AFTER:
            return 0
        if state.stale_told is not None and state.stale_told >= last:
            return 0  # told already for this silence
        notifier = self._notifier() if self._notifier is not None else None
        if notifier is None:
            return 0
        local = last.astimezone(self._watch.zone())
        await notifier.notify(uid, Signal(source="system", kind="watch_stale"), stale_words(local))
        await self._watch.store.mark_told(uid, now)
        return 1


class BodySweep:
    name = SWEEP_JOB
    budget_s = 30.0

    def __init__(
        self,
        watch: WatchService,
        sos: SosStore,
        *,
        keep_days: int,
        now: Callable[[], datetime],
    ) -> None:
        self._watch = watch
        self._sos = sos
        self._keep = keep_days
        self._now = now

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        days = logs = failed = 0
        today = self._watch.today()
        now = self._now()
        now = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
        for uid in owners:
            try:
                if self._watch.sealed:
                    days += await self._watch.store.sweep(
                        uid, keep_from=today - timedelta(days=self._keep - 1)
                    )
                logs += await self._sos.sweep(
                    uid, keep_from=now - timedelta(days=SOS_LOG_DAYS), now=now.timestamp()
                )
            except Exception as exc:  # noqa: BLE001 - one owner never stops another
                log.warning("body sweep failed for an owner", extra={"error": type(exc).__name__})
                failed += 1
        return {"watch_days": days, "sos": logs, FAILED_COUNT: failed}


__all__ = [
    "SOS_LOG_DAYS",
    "STALE_AFTER",
    "STALE_JOB",
    "SWEEP_JOB",
    "BodySweep",
    "WatchStale",
    "stale_words",
]
