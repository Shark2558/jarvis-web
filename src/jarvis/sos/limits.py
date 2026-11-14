# src/jarvis/sos/limits.py
"""The SOS limits (docs/plans/r7-mobile.md D19), split out of `service.py` with no change in what
they do.

A real SOS: 3 an hour and 10 a day; tests and "I'm safe" have their OWN budget, so three tests
never block a real SOS. A slot is taken in one store transaction. A real SOS whose limits cannot be
read still goes out, bounded by an in-process counter (the same numbers); a test is refused. A
press that reached nobody gives its slot back (a real SOS is never refused because earlier presses
failed).

`hourly_cap` and `own_test_budget` are constructor arguments (both on in production): only the
eval's negative controls build a `Limits` with one of them off, so no module-level switch exists.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from jarvis.config import Settings
from jarvis.logging import get_logger
from jarvis.sos.models import Kind
from jarvis.sos.store import DAY_S, Budget, SosOff, SosStore, SosUnavailable

log = get_logger(__name__)

HOUR_S = 3600
STORE_S = 8.0  # the book or the limits: a store that hangs is "unreadable"


@dataclass(frozen=True)
class Slot:
    """Where a press's budget slot was taken, and its stamp (to give it back)."""

    where: Literal["store", "memory"]
    stamp: float


def in_hour(times: Sequence[float], now: float) -> int:
    return sum(1 for t in times if now - t < HOUR_S)


class Limits:
    def __init__(
        self,
        store: SosStore,
        s: Settings,
        *,
        hourly_cap: bool = True,
        own_test_budget: bool = True,
    ) -> None:
        self._store = store
        self._s = s
        self.hourly_cap = hourly_cap
        self.own_test_budget = own_test_budget
        self._mem: dict[str, list[float]] = {}  # the fallback counter: real presses, per owner

    def _decide(self, kind: Kind, now: float) -> Callable[[Budget], str | None]:
        s = self._s

        def decide(b: Budget) -> str | None:
            if kind == "real":
                pool = b.real if self.own_test_budget else (*b.real, *b.test)
                hour, day = s.sos_per_hour, s.sos_per_day
            else:
                pool, hour, day = b.test, s.sos_test_per_hour, s.sos_test_per_day
            if self.hourly_cap and in_hour(pool, now) >= hour:
                return "hour"
            if len(pool) >= day:
                return "day"
            return None

        return decide

    def words(self, kind: Kind, why: str) -> str:
        s = self._s
        if kind == "real":
            n = s.sos_per_hour if why == "hour" else s.sos_per_day
        else:
            n = s.sos_test_per_hour if why == "hour" else s.sos_test_per_day
        if why == "unreadable":
            return "the limit couldn't be checked just now."
        span = "an hour" if why == "hour" else "a day"
        tests = "" if kind == "real" else " tests"
        return f"the limit of {n}{tests} {span} was reached."

    async def take(self, uid: str, kind: Kind, now: float) -> tuple[str | None, Slot | None]:
        """Reserve a slot: (why not, the slot). A real SOS whose limits cannot be read goes out
        anyway, bounded by the in-process counter; a test is refused."""
        pool: Literal["real", "test"] = "real" if kind == "real" else "test"
        try:
            why = await asyncio.wait_for(
                self._store.take(uid, pool, now, self._decide(kind, now)), STORE_S
            )
        except (SosUnavailable, SosOff, TimeoutError) as exc:
            if kind != "real":
                return "unreadable", None
            log.error(
                "SOS limits unreadable: a real SOS goes out, bounded in memory",
                extra={"error": type(exc).__name__},
            )
            return self._take_memory(uid, now)
        return why, (Slot("store", now) if why is None else None)

    def _take_memory(self, uid: str, now: float) -> tuple[str | None, Slot | None]:
        s = self._s
        times = [t for t in self._mem.get(uid, []) if 0 <= now - t < DAY_S]
        why: str | None = None
        if self.hourly_cap and in_hour(times, now) >= s.sos_per_hour:
            why = "hour"
        elif len(times) >= s.sos_per_day:
            why = "day"
        if why is None:
            times.append(now)
        self._mem[uid] = times
        return why, (Slot("memory", now) if why is None else None)

    async def give_back(self, uid: str, kind: Kind, slot: Slot | None, now: float) -> None:
        """A real press that reached nobody does not use up the hour."""
        if kind != "real" or slot is None:
            return
        if slot.where == "memory":
            times = self._mem.get(uid, [])
            if slot.stamp in times:
                times.remove(slot.stamp)
            return
        try:
            await asyncio.wait_for(self._store.give_back(uid, "real", slot.stamp, now), STORE_S)
        except TimeoutError:
            log.warning("an SOS slot was not given back in time")
