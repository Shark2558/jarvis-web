# src/jarvis/home/watchdog.py
"""The laptop watchdog (R3 D9). Cloud only.

`POST /internal/home/watchdog` (Cloud Scheduler, every 5 minutes, 24/7, its own OIDC audience) runs
`Watchdog.run`, which is `ticks.run_jobs` over A's jobs plus the ones I1 adds from B (an arm still
pending after 5 minutes -> `home_arm_failed`) and D (the held-alerts summary when quiet hours end):

- `home_offline`: no heartbeat for `home_offline_after_s` (12 minutes) -> state `offline`; if the
  alarm is armed, ONE `home_offline` alert per outage ("your home laptop stopped answering at
  23:10 - camera alerts are off until it's back"); disarmed -> the state changes, nobody is told.
  The heartbeat handler says "back" (`home_online`). `last_seen` is read from the stored value and
  the in-process one (whichever is newer), so an instance restart can't fake an outage.
- `home_claims_sweep`: event claims older than 48 hours.
- `home_link_sweep`: expired link codes.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

from jarvis.home.ports import ArmReader
from jarvis.home.store import HomeStore
from jarvis.logging import get_logger
from jarvis.notify.ports import Notifier, Signal
from jarvis.ticks import FAILED_COUNT, TickJob, run_jobs

log = get_logger(__name__)


class OfflineJob:
    name = "home_offline"
    budget_s = 30.0

    def __init__(
        self,
        store: HomeStore,
        notifier: Notifier | None,
        arm: ArmReader | None,
        *,
        clock: Callable[[], float],
        offline_after_s: float,
        tz: str = "Asia/Kolkata",
    ) -> None:
        self._store = store
        self._notifier = notifier
        self._arm = arm
        self._clock = clock
        self._after = offline_after_s
        self._tz = ZoneInfo(tz)
        self.last: dict[str, int] = {}

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        counts = {"homes": 0, "offline": 0, "alerts": 0, FAILED_COUNT: 0}
        for uid in owners:
            try:
                await self._one(uid, counts)
            except Exception as exc:  # noqa: BLE001 - one home never stops the others
                log.error("home watchdog failed for a home", extra={"error": type(exc).__name__})
                counts[FAILED_COUNT] += 1
        self.last = counts
        return counts

    async def _one(self, uid: str, counts: dict[str, int]) -> None:
        status = await self._store.status(uid)
        if status is None:
            return
        counts["homes"] += 1
        seen = status.last_seen_at
        if seen is None or self._clock() - seen <= self._after:
            return
        if status.state == "offline":
            counts["offline"] += 1
            return
        armed = False
        if self._arm is not None:
            armed = (await self._arm.view(uid)).armed
        sent = False
        if armed and self._notifier is not None:
            at = datetime.fromtimestamp(seen, self._tz)
            text = (
                f"Your home laptop stopped answering at {at:%H:%M}. "
                "Camera alerts are off until it's back."
            )
            await self._notifier.notify(uid, Signal(source="home", kind="home_offline"), text)
            sent = True
            counts["alerts"] += 1
        await self._store.mark_offline(uid, alerted=sent)
        counts["offline"] += 1


class _Sweep:
    budget_s = 30.0

    def __init__(self, name: str, sweep: Callable[[], object]) -> None:
        self.name = name
        self._sweep = sweep
        self.last: dict[str, int] = {}

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        swept = await self._sweep()  # type: ignore[misc]
        self.last = {"swept": int(swept)}
        return self.last


class Watchdog:
    def __init__(
        self, store: HomeStore, offline: OfflineJob, extra: Sequence[TickJob] = ()
    ) -> None:
        self._store = store
        self._offline = offline
        self._claims = _Sweep("home_claims_sweep", store.sweep_claims)
        self._codes = _Sweep("home_link_sweep", store.sweep_codes)
        self._extra = tuple(extra)

    async def run(self) -> dict[str, object]:
        owners = await self._store.linked_uids()
        jobs: list[TickJob] = [self._offline, self._claims, self._codes, *self._extra]
        results = await run_jobs(jobs, owners)
        return {
            "homes": self._offline.last.get("homes", 0),
            "offline": self._offline.last.get("offline", 0),
            "held_sent": 0,
            "swept": self._claims.last.get("swept", 0) + self._codes.last.get("swept", 0),
            "jobs": results,
        }


__all__ = ["OfflineJob", "Watchdog"]
