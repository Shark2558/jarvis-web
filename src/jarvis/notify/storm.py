# src/jarvis/notify/storm.py
"""Storm control after the decision (R3 D10), in process (one instance).

One intruder alert per camera per 60 s; at most 10 burglar rings per 10 minutes, 20 an hour and
80 a day per owner (inside the Telegram urgent budget of 30 an hour and 100 a day, which also
carries the summaries), then the rest are counted and one summary is due every 10 minutes; one
package alert per 10 minutes; one greeting per person per 30 minutes; a flapping laptop or alarm
(offline, online, arming failed) one alert per 10 minutes.

SAFETY: a hazard (smoke, gas, water) or any emergency decision is never counted in or dropped by
a window. A hazard is only de-duplicated per sensor within 30 s (the same alarm repeating).
Memory is bounded: old keys are pruned.

R11 D5 (docs/plans/r11-free-helpers.md): a disaster alert is treated like a hazard: never capped,
only the same subject (one CAP warning) repeated within 30 minutes is a duplicate. The helpers'
nudges: one per kind per 20 minutes and at most `MAX_NUDGES_PER_HOUR` an hour per owner in all,
a ceiling over the gate's own configured caps (`helpers.gate`), so a fault can't flood Telegram.

R14 D6 (docs/plans/r14-hardening.md, review A6): JARVIS's own health and backup rings have their
own table, apart from the R5.1 soft-urgent one: one per kind and subject per 30 minutes and at
most `MAX_SELF_PER_HOUR` an hour per owner in all, so an outage that fails every job at once can
never crowd out an approval or a systems-check ring.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta

from jarvis.notify.ports import Decision, Signal

INTRUDER_GAP = timedelta(seconds=60)
URGENT_WINDOW = timedelta(minutes=10)
MAX_URGENT_IN_WINDOW = 10
MAX_INTRUDER_PER_HOUR = 20
MAX_INTRUDER_PER_DAY = 80
HAZARD_GAP = timedelta(seconds=30)
FLAP_GAP = timedelta(minutes=10)
FLAP_KINDS = frozenset({"home_offline", "home_offline_idle", "home_online", "home_arm_failed"})
# Health and vitals rings are "urgent" by default but must never crowd out a burglar ring (I2 F2):
# one per subject per 30 minutes and 6 an hour in all, counted apart from the burglar window.
SOFT_URGENT_KINDS = frozenset({"health_fault", "vitals_critical"})
MAX_IDLE_PER_HOUR = 3  # R5.1: a laptop that sleeps and wakes all day rings the idle alert 3 an hour
SOFT_URGENT_GAP = timedelta(minutes=30)
MAX_SOFT_URGENT_PER_HOUR = 6
# R11 D5: the nudge ceiling (the gate keeps the owner's lower caps) and the disaster de-dup
NUDGE_KINDS = frozenset(
    {"nudge_standup", "nudge_hydrate", "nudge_activity", "nudge_free_time", "nudge_focus"}
)
NUDGE_GAP = timedelta(minutes=20)
MAX_NUDGES_PER_HOUR = 8
DISASTER_GAP = timedelta(minutes=30)
# R14 D6: self-health and backups (important daytime rings, held at night)
SELF_KINDS = frozenset(
    {
        "job_failing",
        "clock_stopped",
        "brief_missed",
        "errors_piling",
        "spend_spike",
        "deploy_changed",
        "backup_problem",
    }
)
SELF_GAP = timedelta(minutes=30)
MAX_SELF_PER_HOUR = 3
SUMMARY_EVERY = timedelta(minutes=10)
PACKAGE_GAP = timedelta(minutes=10)
GREETING_GAP = timedelta(minutes=30)
MAX_KEYS = 2000


@dataclass(frozen=True)
class Verdict:
    admit: bool
    reason: str = "ok"


class Storm:
    def __init__(self) -> None:
        self._intruder: dict[tuple[str, str], datetime] = {}
        self._urgent: dict[str, deque[datetime]] = {}  # burglar rings only, last 24 h
        self._hazard: dict[tuple[str, str], datetime] = {}
        self._flap: dict[tuple[str, str], datetime] = {}
        self._soft: dict[tuple[str, str, str], datetime] = {}  # (uid, kind, subject) gap stamps
        self._soft_rings: dict[str, deque[datetime]] = {}  # uid -> health/vitals rings, last hour
        self._idle: dict[str, deque[datetime]] = {}  # uid -> idle-offline rings, last hour
        self._pending: dict[str, tuple[int, datetime]] = {}  # uid -> (suppressed, first at)
        self._package: dict[str, datetime] = {}
        self._greeting: dict[tuple[str, str], datetime] = {}
        self._nudge: dict[tuple[str, str], datetime] = {}  # (uid, kind) -> last nudge (R11)
        self._nudges: dict[str, deque[datetime]] = {}  # uid -> nudges in the last hour (R11)
        self._disaster: dict[tuple[str, str], datetime] = {}  # (uid, subject) -> last (R11)
        self._self: dict[tuple[str, str, str], datetime] = {}  # (uid, kind, subject) (R14)
        self._self_rings: dict[str, deque[datetime]] = {}  # uid -> self-health rings, last hour
        # what a gap stamp was before the last admission set it (for `rollback`), by table
        self._before: dict[tuple[str, str, str], datetime | None] = {}

    def _stamp(
        self, tag: str, table: dict[tuple[str, str], datetime], key: tuple[str, str], now: datetime
    ) -> None:
        if len(self._before) > MAX_KEYS:
            self._before.clear()
        self._before[(tag, *key)] = table.get(key)
        table[key] = now

    def rollback(self, uid: str, signal: Signal, now: datetime) -> None:
        """A burglar ring or a laptop/arming alert admitted at `now` reached no channel: give its
        slot back, so the retry (the bridge's, or the watchdog's next run) is not swallowed as a
        storm or a flap (integrated review S3). A later admission is never undone."""
        if signal.kind in SOFT_URGENT_KINDS:
            self._rollback_soft(uid, signal, now)
            return
        if signal.kind in SELF_KINDS:
            self._rollback_self(uid, signal, now)
            return
        if signal.kind in NUDGE_KINDS:
            self._rollback_nudge(uid, signal, now)
            return
        if signal.kind == "disaster_alert":
            key = (uid, signal.subject or "-")
            if self._disaster.get(key) == now:
                del self._disaster[key]
            return
        if signal.kind == "home_intruder":
            tag, key, table = "intruder", (uid, signal.camera or "-"), self._intruder
        elif signal.kind in FLAP_KINDS:
            tag, key, table = "flap", (uid, signal.kind), self._flap
        else:
            return
        if signal.kind == "home_offline_idle":
            idle = self._idle.get(uid)
            if idle is not None and now in idle:
                idle.remove(now)
        if table.get(key) != now or (tag, *key) not in self._before:
            return
        before = self._before.pop((tag, *key))
        if before is None:
            del table[key]
        else:
            table[key] = before
        window = self._urgent.get(uid) if signal.kind == "home_intruder" else None
        if window is not None and now in window:
            window.remove(now)

    def _idle_ok(self, uid: str, now: datetime) -> bool:
        window = self._idle.setdefault(uid, deque())
        while window and now - window[0] >= timedelta(hours=1):
            window.popleft()
        if len(window) >= MAX_IDLE_PER_HOUR:
            return False
        window.append(now)
        if len(self._idle) > MAX_KEYS:
            self._idle = {k: v for k, v in self._idle.items() if v}
        return True

    def _rollback_nudge(self, uid: str, signal: Signal, now: datetime) -> None:
        key = (uid, signal.kind)
        if self._nudge.get(key) == now:
            del self._nudge[key]
        window = self._nudges.get(uid)
        if window is not None and now in window:
            window.remove(now)

    def _nudge_ok(self, uid: str, signal: Signal, now: datetime) -> Verdict:
        """R11 D5: one nudge per kind per 20 minutes, `MAX_NUDGES_PER_HOUR` an hour in all."""
        key = (uid, signal.kind)
        last = self._nudge.get(key)
        if last is not None and now - last < NUDGE_GAP:
            return Verdict(False, "nudge_gap")
        window = self._nudges.setdefault(uid, deque())
        while window and now - window[0] >= timedelta(hours=1):
            window.popleft()
        if len(window) >= MAX_NUDGES_PER_HOUR:
            return Verdict(False, "nudge_cap")
        window.append(now)
        self._nudge[key] = now
        self._prune(self._nudge, now, NUDGE_GAP)
        if len(self._nudges) > MAX_KEYS:
            self._nudges = {k: v for k, v in self._nudges.items() if v}
        return Verdict(True)

    def _disaster_ok(self, uid: str, signal: Signal, now: datetime) -> Verdict:
        """R11 D5: never capped; only the same warning again within 30 minutes is a duplicate."""
        key = (uid, signal.subject or "-")
        last = self._disaster.get(key)
        if signal.subject is not None and last is not None and now - last < DISASTER_GAP:
            return Verdict(False, "duplicate")
        self._disaster[key] = now
        self._prune(self._disaster, now, DISASTER_GAP)
        return Verdict(True)

    def _rollback_soft(self, uid: str, signal: Signal, now: datetime) -> None:
        key = (uid, signal.kind, signal.subject or "-")
        if self._soft.get(key) == now:
            del self._soft[key]
        window = self._soft_rings.get(uid)
        if window is not None and now in window:
            window.remove(now)

    def _soft_ok(self, uid: str, signal: Signal, now: datetime) -> Verdict:
        """Health / vitals urgent rings: a gap per subject, then an hourly cap of their own."""
        key = (uid, signal.kind, signal.subject or "-")
        last = self._soft.get(key)
        if last is not None and now - last < SOFT_URGENT_GAP:
            return Verdict(False, "flap_gap")
        window = self._soft_rings.setdefault(uid, deque())
        while window and now - window[0] >= timedelta(hours=1):
            window.popleft()
        if len(window) >= MAX_SOFT_URGENT_PER_HOUR:
            return Verdict(False, "soft_cap")
        window.append(now)
        self._soft[key] = now
        self._prune(self._soft, now, SOFT_URGENT_GAP)
        return Verdict(True)

    def _rollback_self(self, uid: str, signal: Signal, now: datetime) -> None:
        key = (uid, signal.kind, signal.subject or "-")
        if self._self.get(key) == now:
            del self._self[key]
        window = self._self_rings.get(uid)
        if window is not None and now in window:
            window.remove(now)

    def _self_ok(self, uid: str, signal: Signal, now: datetime) -> Verdict:
        """R14 D6: a gap per kind and subject, then an hourly cap of their own."""
        key = (uid, signal.kind, signal.subject or "-")
        last = self._self.get(key)
        if last is not None and now - last < SELF_GAP:
            return Verdict(False, "self_gap")
        window = self._self_rings.setdefault(uid, deque())
        while window and now - window[0] >= timedelta(hours=1):
            window.popleft()
        if len(window) >= MAX_SELF_PER_HOUR:
            return Verdict(False, "self_cap")
        window.append(now)
        self._self[key] = now
        self._prune(self._self, now, SELF_GAP)
        if len(self._self_rings) > MAX_KEYS:
            self._self_rings = {k: v for k, v in self._self_rings.items() if v}
        return Verdict(True)

    @staticmethod
    def _prune(table: dict, now: datetime, keep: timedelta) -> None:  # type: ignore[type-arg]
        if len(table) <= MAX_KEYS:
            return
        for key in [k for k, at in table.items() if now - at > keep]:
            del table[key]

    def _suppress(self, uid: str, now: datetime) -> Verdict:
        count, since = self._pending.get(uid, (0, now))
        self._pending[uid] = (count + 1, since)
        return Verdict(False, "storm")

    def note_suppressed(self, uid: str, now: datetime) -> None:
        """An urgent alert that a channel refused (a cap) joins the next summary."""
        self._suppress(uid, now)

    def _hazard_ok(self, uid: str, signal: Signal, now: datetime) -> bool:
        if signal.camera is None:  # unknown sensor: never de-duplicate
            return True
        key = (uid, signal.camera)
        last = self._hazard.get(key)
        if last is not None and now - last < HAZARD_GAP:
            return False
        self._hazard[key] = now
        self._prune(self._hazard, now, HAZARD_GAP)
        return True

    def _intruder_window_ok(self, uid: str, now: datetime) -> bool:
        window = self._urgent.setdefault(uid, deque())
        while window and now - window[0] >= timedelta(days=1):
            window.popleft()
        recent = [at for at in window if now - at < URGENT_WINDOW]
        hour = sum(1 for at in window if now - at < timedelta(hours=1))
        if (
            len(recent) >= MAX_URGENT_IN_WINDOW
            or hour >= MAX_INTRUDER_PER_HOUR
            or len(window) >= MAX_INTRUDER_PER_DAY
        ):
            return False
        window.append(now)
        if len(self._urgent) > MAX_KEYS:
            self._urgent = {k: v for k, v in self._urgent.items() if v}
        return True

    def admit(self, uid: str, signal: Signal, decision: Decision, now: datetime) -> Verdict:
        """Whether this ring or silent alert goes out. Only call it for ring / silent."""
        kind = signal.kind
        if kind == "home_hazard" or decision.reason == "emergency":
            if kind == "home_hazard" and not self._hazard_ok(uid, signal, now):
                return Verdict(False, "duplicate")
            return Verdict(True)
        if kind in SOFT_URGENT_KINDS:
            return self._soft_ok(uid, signal, now)
        if kind in SELF_KINDS:
            return self._self_ok(uid, signal, now)
        if kind == "disaster_alert":
            return self._disaster_ok(uid, signal, now)
        if kind in NUDGE_KINDS:
            return self._nudge_ok(uid, signal, now)
        if kind in FLAP_KINDS:
            flap = (uid, kind)
            last_f = self._flap.get(flap)
            if last_f is not None and now - last_f < FLAP_GAP:
                return Verdict(False, "flap_gap")
            if kind == "home_offline_idle" and not self._idle_ok(uid, now):
                return Verdict(False, "flap_gap")
            self._stamp("flap", self._flap, flap, now)
        if kind == "home_intruder":
            key = (uid, signal.camera or "-")
            last = self._intruder.get(key)
            if last is not None and now - last < INTRUDER_GAP:
                return self._suppress(uid, now)
            self._stamp("intruder", self._intruder, key, now)
            self._prune(self._intruder, now, INTRUDER_GAP)
        if kind == "home_package":
            last_pkg = self._package.get(uid)
            if last_pkg is not None and now - last_pkg < PACKAGE_GAP:
                return Verdict(False, "package_gap")
            self._package[uid] = now
            self._prune(self._package, now, PACKAGE_GAP)
        if kind == "home_greeting":
            who = (uid, signal.person_ref or "-")
            last_g = self._greeting.get(who)
            if last_g is not None and now - last_g < GREETING_GAP:
                return Verdict(False, "greeting_gap")
            self._greeting[who] = now
            self._prune(self._greeting, now, GREETING_GAP)
        if kind == "home_intruder" and decision.action == "ring":
            if not self._intruder_window_ok(uid, now):
                return self._suppress(uid, now)
        return Verdict(True)

    def due_summary(self, uid: str, now: datetime) -> int:
        """How many alerts were suppressed if a summary is due (and reset), else 0."""
        got = self._pending.get(uid)
        if got is None or now - got[1] < SUMMARY_EVERY:
            return 0
        del self._pending[uid]
        return got[0]

    def owners_with_pending(self) -> list[str]:
        return list(self._pending)


def summary_text(count: int) -> str:
    n = max(1, count)
    more = "1 more alert" if n == 1 else f"{n} more alerts"
    return f"{more} from your cameras in the last 10 minutes - open JARVIS, then Home."


__all__ = [
    "DISASTER_GAP",
    "MAX_NUDGES_PER_HOUR",
    "MAX_SELF_PER_HOUR",
    "NUDGE_GAP",
    "NUDGE_KINDS",
    "SELF_GAP",
    "SELF_KINDS",
    "SOFT_URGENT_KINDS",
    "Storm",
    "Verdict",
    "summary_text",
]
