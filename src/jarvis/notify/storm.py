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
FLAP_KINDS = frozenset({"home_offline", "home_online", "home_arm_failed"})
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
        self._pending: dict[str, tuple[int, datetime]] = {}  # uid -> (suppressed, first at)
        self._package: dict[str, datetime] = {}
        self._greeting: dict[tuple[str, str], datetime] = {}

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
        if kind in FLAP_KINDS:
            flap = (uid, kind)
            last_f = self._flap.get(flap)
            if last_f is not None and now - last_f < FLAP_GAP:
                return Verdict(False, "flap_gap")
            self._flap[flap] = now
        if kind == "home_intruder":
            key = (uid, signal.camera or "-")
            last = self._intruder.get(key)
            if last is not None and now - last < INTRUDER_GAP:
                return self._suppress(uid, now)
            self._intruder[key] = now
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


__all__ = ["Storm", "Verdict", "summary_text"]
