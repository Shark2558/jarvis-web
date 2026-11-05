# src/jarvis/notify/storm.py
"""Storm control after the decision (R3 D10), in process (one instance).

One intruder alert per camera per 60 s; at most 10 urgent rings per 10 minutes per owner, then
the rest are counted and one summary is due every 10 minutes; one package alert per 10 minutes;
one greeting per person per 30 minutes. Memory is bounded: old keys are pruned.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta

from jarvis.notify.ports import Decision, Signal

INTRUDER_GAP = timedelta(seconds=60)
URGENT_WINDOW = timedelta(minutes=10)
MAX_URGENT_IN_WINDOW = 10
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
        self._urgent: dict[str, deque[datetime]] = {}
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

    def admit(self, uid: str, signal: Signal, decision: Decision, now: datetime) -> Verdict:
        """Whether this ring or silent alert goes out. Only call it for ring / silent."""
        kind = signal.kind
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
        if decision.action == "ring" and decision.urgency == "urgent" and kind != "home_summary":
            window = self._urgent.setdefault(uid, deque())
            while window and now - window[0] >= URGENT_WINDOW:
                window.popleft()
            if len(window) >= MAX_URGENT_IN_WINDOW:
                return self._suppress(uid, now)
            window.append(now)
            if len(self._urgent) > MAX_KEYS:
                self._urgent = {k: v for k, v in self._urgent.items() if v}
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
