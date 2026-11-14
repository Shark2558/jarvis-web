# src/jarvis/watch/jobs.py
"""Part D's background jobs (docs/plans/r7-mobile.md D17, D25; I0 seam 20). No model, no value in
a log line: counts only.

- `WatchStale` (the helpers' 5-minute clock, `watch_stale`): the owner is told ONCE (an `info`
  alert, silent) per silence, until it ends, when (a) a phone that synced has been silent for
  `STALE_AFTER` (26 hours: the app syncs every 6 hours and when opened), (b) a phone whose syncs
  are ALL refused has tried for that long, or (c) the phone syncs but no watch data (an empty or
  old day) has arrived for `DATA_STALE_DAYS` days, or (d) a phone LINKED that long ago has neither
  synced nor tried (I1: the link time comes from Part C's `services["linked_since"]`; without it,
  or when it can't be read, such a phone is not known here and never told about). "Told" is only
  a real delivery (ring or silent, to a
  channel): a held or dropped notice is tried again after an hour, and a notice that went out but
  could not be noted is never sent again by this process. No notifier is logged and counted
  (`no_notifier`).
- `BodySweep` (the morning tick, `body_sweep`): watch days older than `watch_keep_days` (400),
  SOS log entries older than 400 days and join words that ran out.
Each owner is served on his own: one owner's failure is counted (`failed`) and stops no one.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, date, datetime, time, timedelta

from jarvis.logging import get_logger
from jarvis.notify.ports import Delivery, Notifier, Signal
from jarvis.sos.store import SosStore
from jarvis.ticks import FAILED_COUNT
from jarvis.watch.service import WatchService
from jarvis.watch.store import WatchState

log = get_logger(__name__)
STALE_AFTER = timedelta(hours=26)
DATA_STALE_DAYS = 3  # a phone that syncs but sends no data for this many days
RETRY_AFTER = timedelta(hours=1)  # a held or dropped notice is tried again this much later
SOS_LOG_DAYS = 400
STALE_JOB, SWEEP_JOB = "watch_stale", "body_sweep"


def stale_words(local: datetime) -> str:
    return (
        f"Your phone hasn't sent your watch data since {local.day} {local.strftime('%b')}, "
        f"{local.strftime('%H:%M')}, Sir. Open the JARVIS app on your phone to sync."
    )


def refused_words(local: datetime) -> str:
    return (
        f"Your phone has tried to send your watch data since {local.day} {local.strftime('%b')}, "
        "Sir, but JARVIS refused it each time. Please update the JARVIS app on your phone."
    )


def no_data_words(day: date) -> str:
    return (
        f"Your phone is syncing, Sir, but no watch data has arrived since {day.day} "
        f"{day.strftime('%b')}. Check that your watch is connected to Health Connect."
    )


def never_words(local: datetime) -> str:
    return (
        f"Your phone was linked on {local.day} {local.strftime('%b')}, "
        f"{local.strftime('%H:%M')}, but it hasn't sent any watch data yet, Sir. Open the JARVIS "
        "app on your phone and allow it to read Health Connect."
    )


LinkedSince = Callable[[str], Awaitable[float | None]]


def _utc(at: datetime) -> datetime:
    return at if at.tzinfo is not None else at.replace(tzinfo=UTC)


class WatchStale:
    name = STALE_JOB
    budget_s = 10.0

    def __init__(
        self,
        watch: WatchService,
        *,
        notifier: Callable[[], Notifier | None] | None,
        now: Callable[[], datetime],
        linked: Callable[[], LinkedSince | None] | None = None,
    ) -> None:
        self._watch = watch
        self._notifier = notifier
        self._now = now
        self._linked = linked  # Part C's link-time seam, read late (I1)
        # per owner: (the silence's moment, when it was tried, delivered). In this process only.
        self._tried: dict[str, tuple[datetime, datetime, bool]] = {}

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        told = failed = silent = 0
        if not self._watch.enabled or not self._watch.sealed:
            return {"told": 0, "no_notifier": 0, FAILED_COUNT: 0}
        now = _utc(self._now())
        for uid in owners:
            try:
                got = await self._one(uid, now)
            except Exception as exc:  # noqa: BLE001 - one owner never stops another
                log.warning("watch_stale failed for an owner", extra={"error": type(exc).__name__})
                failed += 1
                continue
            told += got in ("told", "told_unnoted")
            failed += got == "told_unnoted"
            silent += got == "no_notifier"
        return {"told": told, "no_notifier": silent, FAILED_COUNT: failed}

    async def _link_state(self, uid: str) -> tuple[bool, datetime | None]:
        """(known, when his first phone was linked) from Part C's seam. `known` is False when the
        seam is missing or unreadable (nobody can say); known with no time means NO phone is
        linked (the owner unlinked it on purpose, or never linked one)."""
        read = self._linked() if self._linked is not None else None
        if not callable(read):
            return False, None
        try:
            at = await read(uid)
        except Exception as exc:  # noqa: BLE001 - an unknown link time is "not known", never told
            log.warning("the phone's link time unreadable", extra={"error": type(exc).__name__})
            return False, None
        if isinstance(at, bool) or not isinstance(at, int | float):
            return True, None
        return True, datetime.fromtimestamp(at, UTC)

    def _silence(
        self, state: WatchState, now: datetime, linked: datetime | None = None
    ) -> tuple[datetime, str] | None:
        """The moment the silence counts from, and its kind; None when all is well."""
        last, zone = state.last_sync, self._watch.zone()
        if last is not None and now - last >= STALE_AFTER:
            return last, "sync"
        if last is None and state.first_refused and now - state.first_refused >= STALE_AFTER:
            return state.first_refused, "refused"
        if last is not None:
            base = state.last_data_day or (state.first_sync or last).astimezone(zone).date()
            if (now.astimezone(zone).date() - base).days >= DATA_STALE_DAYS:
                return datetime.combine(base, time.min, tzinfo=UTC), "data"
        elif state.first_refused is None and linked is not None and now - linked >= STALE_AFTER:
            return linked, "never"
        return None

    async def _one(self, uid: str, now: datetime) -> str:
        known, linked = await self._link_state(uid)
        if known and linked is None:
            return ""  # no phone is linked (unlinked on purpose): nothing to be silent about
        state = await self._watch.state(uid)
        never = state.last_sync is None and state.first_refused is None
        found = self._silence(state, now, linked if never else None)
        if found is None:
            return ""
        ref, kind = found
        if state.stale_told is not None and state.stale_told == ref:
            return ""  # told already for this silence
        tried = self._tried.get(uid)
        if tried is not None and tried[0] == ref and (tried[2] or now - tried[1] < RETRY_AFTER):
            return ""  # delivered but not noted, or held a moment ago
        notifier = self._notifier() if self._notifier is not None else None
        if notifier is None:
            log.warning("no notifier: the watch alert was not sent")
            return "no_notifier"
        local = ref.astimezone(self._watch.zone())
        words = {"sync": stale_words, "refused": refused_words, "never": never_words}.get(kind)
        said = words(local) if words else no_data_words(local.date())
        got = await notifier.notify(uid, Signal(source="system", kind="watch_stale"), said)
        real = (
            isinstance(got, Delivery)
            and got.action in ("ring", "silent")
            and (got.telegram or got.push > 0)
        )
        self._tried[uid] = (ref, now, bool(real))
        if not real:
            log.warning("the watch alert was held or reached no device: tried again later")
            return "held"
        try:
            await self._watch.store.mark_told(uid, ref)
        except Exception as exc:  # noqa: BLE001 - told; the failure to note it is counted
            log.error("the watch alert was sent but not noted", extra={"error": type(exc).__name__})
            return "told_unnoted"  # `_tried` stops this process telling again every 5 minutes
        return "told"


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
