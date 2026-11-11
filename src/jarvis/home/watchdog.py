# src/jarvis/home/watchdog.py
"""The laptop watchdog (R3 D9; R5.1 D3). Cloud only.

`POST /internal/home/watchdog` (Cloud Scheduler, every 5 minutes, 24/7, its own OIDC audience) runs
`Watchdog.run`, which is `ticks.run_jobs` over A's jobs plus the ones I1 adds from B (an arm still
pending after 5 minutes -> `home_arm_failed`), D (the held-alerts summary when quiet hours end) and,
from R5.1, the shared systems-check job (`health.tick.HealthTickJob`, D4):

- `home_offline`: no heartbeat for `home_offline_after_s` (360 s: 3 missed beats) -> state
  `offline`, and ONE alert per outage:
  - armed: `home_offline` ("your home laptop stopped answering at 23:10 - camera alerts are off
    until it's back"), urgent (it rings through quiet hours). Only an alert Telegram or a browser
    took counts (integrated review H5); one that no channel took is tried again at the next run.
  - disarmed, `alert_when="always"` (the default, R5.1 D3): `home_offline_idle` ("... The camera
    and home devices are off until it's back, Sir."), important: it rings in waking hours even
    when only urgent things ring, and is HELD in quiet hours. A held alert counts as told (the
    held summary carries it; sending again every 5 minutes would add one more "laptop offline" to
    that summary each run), and so does one the owner switched off or to feed-only; any other
    alert no channel took (a storm gap, nobody reachable) is tried again at the next run.
  - disarmed, `alert_when="armed_only"`: the R3 behaviour; the state changes, nobody is told.
  - arming during an outage already told as idle: the urgent `home_offline` goes out once, so the
    owner hears "camera alerts are off" (the armed alert is never blocked by an earlier idle
    one). The kind told is stored with the outage (`HomeStore.mark_offline(kind=)`, R5.1 I1), so
    a restart or another instance keeps "idle told, armed not yet"; an outage told before R5.1
    (no kind stored) was told by the armed alert and stays settled.
  The heartbeat handler says "back" (`home_online`) when an outage alert had gone out. `last_seen`
  is read from the stored value and the in-process one (whichever is newer), so an instance
  restart can't fake an outage.
- `home_claims_sweep`: event claims older than 48 hours.
- `home_link_sweep`: expired link codes.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Literal, get_args
from zoneinfo import ZoneInfo

from jarvis.alerts import AlertKind
from jarvis.home.models import HomeStatus, OutageKind
from jarvis.home.ports import ArmReader
from jarvis.home.store import HomeStore
from jarvis.logging import get_logger
from jarvis.notify.ports import Delivery, Notifier, Signal
from jarvis.ticks import FAILED_COUNT, TickJob, run_jobs

log = get_logger(__name__)

AlertWhen = Literal["always", "armed_only"]
ARMED_TEXT = "Your home laptop stopped answering at {at}. Camera alerts are off until it's back."
IDLE_TEXT = (
    "Your home laptop stopped answering at {at}. The camera and home devices are off until "
    "it's back, Sir."
)
# The owner's own choice for the kind: nothing to retry, the outage is settled as told.
OWNER_SETTLED = frozenset({"switched_off", "feed_only"})
# The whole run, under the Scheduler's --attempt-deadline of 60 s (deploy/cloudrun.sh) with room
# to answer (R6 review L4): a job the run has no time left for is cut ("degraded" when advisory),
# and the next run in 5 minutes tries again.
WATCHDOG_BUDGET_S = 50.0


def took(delivery: Delivery, *, idle: bool) -> bool:
    """Whether this outage now counts as told. A channel took it: always. For the idle alert also
    a HELD one (the held summary carries it to the morning) and one the owner switched off."""
    if delivery.telegram or delivery.push:
        return True
    if not idle:
        return False  # armed: unchanged (integrated review H5)
    if delivery.action == "hold":
        return True
    return delivery.action == "drop" and delivery.reason in OWNER_SETTLED


# Jobs that ride the watchdog but are not the laptop watchdog: when one fails the Scheduler must
# not see the 5-minute laptop check as failing (and retry it). They report "degraded" instead.
# R6: a build book seal over the storage limit fails every run until the owner raises it (he is
# told once) and a sweep retries its deletes by itself: neither may 503 the watchdog
# R11 D3: the helpers' 5-minute clock rides here too; its reminders never fail the laptop check
ADVISORY_JOBS = frozenset({"health_check", "book_seal", "book_sweep", "helpers_clock"})


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
        alert_when: AlertWhen = "always",
    ) -> None:
        if alert_when not in get_args(AlertWhen):
            raise ValueError("alert_when must be 'always' or 'armed_only'")
        self._store = store
        self._notifier = notifier
        self._arm = arm
        self._clock = clock
        self._after = offline_after_s
        self._tz = ZoneInfo(tz)
        self._alert_when: AlertWhen = alert_when
        self.last: dict[str, int] = {}
        # owners whose current outage was told as idle only (also stored: `outage_kind`)
        self._told_idle: set[str] = set()

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
            self._told_idle.discard(uid)  # the outage is over
            return
        counts["offline"] += 1
        settled = status.state == "offline" and status.outage_alerted
        if settled and not self._idle_only(uid, status):
            return  # once per outage
        armed = False
        if self._arm is not None:
            armed = (await self._arm.view(uid)).armed
        if settled and not armed:
            return  # told as idle, still disarmed
        told = False
        if self._notifier is not None and (armed or self._alert_when == "always"):
            sent = await self._claim_and_tell(self._notifier, uid, seen, armed, counts)
            if sent is None:
                return  # another instance holds the alert slot (compare-and-set in the store)
            told = sent
        if told and armed:
            self._told_idle.discard(uid)
        elif told:
            self._told_idle.add(uid)
        if settled:  # an idle alert had gone out; the armed one now has too (or is retried)
            if told:
                await self._store.mark_offline(uid, alerted=True, kind="armed")
            return
        if status.state != "offline" or told:
            kind: OutageKind | None = ("armed" if armed else "idle") if told else None
            await self._store.mark_offline(uid, alerted=told, kind=kind)

    async def _claim_and_tell(
        self, notifier: Notifier, uid: str, seen: float, armed: bool, counts: dict[str, int]
    ) -> bool | None:
        """Take the alert slot (store compare-and-set), send, and give the slot back when no
        channel took the alert. None: not ours to send."""
        if not await self._store.claim_alert(uid, "armed" if armed else "idle"):
            return None
        try:
            told = await self._tell(notifier, uid, seen, armed=armed, counts=counts)
        except BaseException:
            await self._store.release_claim(uid)
            raise
        if not told:
            await self._store.release_claim(uid)
        return told

    def _idle_only(self, uid: str, status: HomeStatus) -> bool:
        """Whether this outage was told by the idle alert only: the stored kind (any instance),
        else this process's memory (a record written before the kind was stored)."""
        if status.outage_kind is not None:
            return status.outage_kind == "idle"
        return uid in self._told_idle

    async def _tell(
        self, notifier: Notifier, uid: str, seen: float, *, armed: bool, counts: dict[str, int]
    ) -> bool:
        at = f"{datetime.fromtimestamp(seen, self._tz):%H:%M}"
        kind: AlertKind = "home_offline" if armed else "home_offline_idle"
        text = (ARMED_TEXT if armed else IDLE_TEXT).format(at=at)
        got = await notifier.notify(uid, Signal(source="home", kind=kind), text)
        counts["alerts"] += int(bool(got.telegram or got.push))
        return took(got, idle=not armed)


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
        self,
        store: HomeStore,
        offline: OfflineJob,
        extra: Sequence[TickJob] = (),
        *,
        budget_s: float = WATCHDOG_BUDGET_S,
    ) -> None:
        self._store = store
        self._offline = offline
        self._budget_s = budget_s
        self._claims = _Sweep("home_claims_sweep", store.sweep_claims)
        self._codes = _Sweep("home_link_sweep", store.sweep_codes)
        self._extra = tuple(extra)

    def extend(self, job: TickJob) -> None:
        """Add a job built after the watchdog (R5.1 D4: the shared systems-check job, which
        `wire_r4` builds after home wiring). A name already in the list is refused."""
        jobs: list[TickJob] = [self._offline, self._claims, self._codes, *self._extra]
        names = {j.name for j in jobs}
        if job.name in names:
            raise ValueError(f"the watchdog already runs a job named {job.name}")
        self._extra = (*self._extra, job)

    async def run(self) -> dict[str, object]:
        owners = await self._store.linked_uids()
        jobs: list[TickJob] = [self._offline, self._claims, self._codes, *self._extra]
        results: dict[str, str] = dict(await run_jobs(jobs, owners, total_budget_s=self._budget_s))
        for name in ADVISORY_JOBS & results.keys():  # int-sec M4: never a 503 for these
            if results[name] == "failed":
                log.error("an advisory watchdog job did not finish", extra={"job": name})
                results[name] = "degraded"
        return {
            "homes": self._offline.last.get("homes", 0),
            "offline": self._offline.last.get("offline", 0),
            "held_sent": 0,
            "swept": self._claims.last.get("swept", 0) + self._codes.last.get("swept", 0),
            "jobs": results,
        }


__all__ = [
    "ADVISORY_JOBS",
    "WATCHDOG_BUDGET_S",
    "ARMED_TEXT",
    "IDLE_TEXT",
    "AlertWhen",
    "OfflineJob",
    "Watchdog",
    "took",
]
