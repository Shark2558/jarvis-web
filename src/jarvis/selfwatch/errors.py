# src/jarvis/selfwatch/errors.py
"""Errors piling up (docs/plans/r14-hardening.md D5, review A6): a `logging.Handler` the wiring
installs once on the root logger (`services["log_handler"]`).

- It counts ERROR (and CRITICAL) records by the hour of the day and by logger name: counts and
  names only, never a message, an argument or a traceback.
- It never counts its own package's records (`jarvis.selfwatch*`), and while a self-health alert
  is being sent (`ports.SENDING`) it leaves out the notifier's and Telegram's (`QUIET_LOGGERS`):
  telling the owner about errors can never make more of them.
- It never fails out loud: `emit` catches everything and only counts the record it could not
  count (`unrecorded`, which the 5-minute job reports as a failed step and the status shows);
  the stdlib's `handleError` (a traceback to stderr) is switched off.
- The counts wait in memory and the 5-minute job writes them, batched, to
  `{prefix}selfwatch_errors/{yyyymmdd}` (the owner's local day): `{hours: {"HH": n}, loggers:
  {name: n} (at most `MAX_NAMES`), other: n}`, kept 14 days (`write_counts`; the stdlib's own
  `flush()` is left alone: `logging.shutdown` calls it). A write that fails keeps them for the
  next one.
- `Piles`: the days with an hour over the limit still to be said. An hour that piled up while a
  told job streak ran is that incident's (said once, by `job_failing`) and never owed; any
  other hot day is owed until its alert is settled.
"""

from __future__ import annotations

import logging
import re
import threading
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from jarvis.selfwatch.ports import QUIET_LOGGERS, SENDING
from jarvis.storage.docs import Delete, Docs, DocTx, Query

OWN = "jarvis.selfwatch"
MAX_NAMES = 50
MAX_PENDING_DAYS = 7  # a store down for days keeps at most this many days in memory
KEEP_DAYS = 14
_NAME = re.compile(r"[A-Za-z0-9_.-]{1,100}")
Counts = dict[str, dict[str, Any]]


def _under(name: str, package: str) -> bool:
    """The logger `package` itself or one below it (never a lookalike such as `packagex`)."""
    return name == package or name.startswith(package + ".")


def _int(v: object) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else 0


def worst_hour(doc: dict[str, Any]) -> int:
    hours = doc.get("hours")
    return max((_int(v) for v in hours.values()), default=0) if isinstance(hours, dict) else 0


def over(doc: dict[str, Any], threshold: int) -> bool:
    """More than `threshold` errors in one hour of that day."""
    return worst_hour(doc) > threshold


def hot_hours(doc: dict[str, Any], threshold: int) -> set[str]:
    """The hours of that day with more than `threshold` errors."""
    hours = doc.get("hours")
    if not isinstance(hours, dict):
        return set()
    return {str(h) for h, v in hours.items() if _int(v) > threshold}


def _newest(table: dict[str, Any] | set[str]) -> list[str]:
    return sorted(table)[:-MAX_PENDING_DAYS]  # the keys to drop: all but the newest week


class Piles:
    """Days owed an `errors_piling`; the hot hours a told incident already covers."""

    def __init__(self) -> None:
        self._covered: dict[str, set[str]] = {}
        self._owed: set[str] = set()

    def see(self, written: Counts, threshold: int, *, held: bool) -> None:
        for day, doc in written.items():
            hot = hot_hours(doc, threshold)
            if held:
                self._covered.setdefault(day, set()).update(hot)
            elif hot - self._covered.get(day, set()):
                self._owed.add(day)
        for day in _newest(self._covered):
            del self._covered[day]
        self._owed.difference_update(_newest(self._owed))

    def owed(self) -> list[str]:
        return sorted(self._owed)

    def settle(self, day: str) -> None:
        self._owed.discard(day)


def _add(into: dict[str, Any], more: dict[str, Any]) -> dict[str, Any]:
    """A new day document: `into` plus `more` (names past `MAX_NAMES` go to `other`)."""
    hours = {k: _int(v) for k, v in (into.get("hours") or {}).items() if _int(v)}
    for k, v in more.get("hours", {}).items():
        hours[k] = hours.get(k, 0) + v
    names = {k: _int(v) for k, v in (into.get("loggers") or {}).items() if _int(v)}
    other = _int(into.get("other")) + _int(more.get("other"))
    for k, v in more.get("loggers", {}).items():
        if k in names or len(names) < MAX_NAMES:
            names[k] = names.get(k, 0) + v
        else:
            other += v
    out: dict[str, Any] = {"hours": hours, "loggers": names}
    if other:
        out["other"] = other
    return out


class ErrorCounter(logging.Handler):
    def __init__(self, *, tz: ZoneInfo, prefix: str = "jarvis_") -> None:
        super().__init__(level=logging.ERROR)
        self._tz = tz
        self._coll = f"{prefix}selfwatch_errors"
        self._pending: Counts = {}
        self._mu = threading.Lock()  # the counts between `emit` (any thread) and the writer
        self._unrecorded = 0  # records it could not count
        self._reported = 0  # of them, already reported by `new_unrecorded`

    @property
    def unrecorded(self) -> int:
        return self._unrecorded

    @property
    def broken(self) -> bool:
        return self._unrecorded > 0

    def new_unrecorded(self) -> int:
        """The records it could not count since the last call."""
        new, self._reported = self._unrecorded - self._reported, self._unrecorded
        return new

    @staticmethod
    def _skip(name: str) -> bool:
        if _under(name, OWN):
            return True
        return SENDING.get() and any(_under(name, q) for q in QUIET_LOGGERS)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            name = record.name if isinstance(record.name, str) else ""
            if record.levelno < logging.ERROR or self._skip(name):
                return
            at = datetime.fromtimestamp(record.created, self._tz)
            day, hour = f"{at:%Y%m%d}", f"{at:%H}"
            key = name if _NAME.fullmatch(name) else ""
            one = {"hours": {hour: 1}, "loggers": {key: 1} if key else {}, "other": 0 if key else 1}
            with self._mu:
                if day in self._pending or len(self._pending) < MAX_PENDING_DAYS:
                    self._pending[day] = _add(self._pending.get(day, {}), one)
        except Exception:  # noqa: BLE001 - a handler that fails never logs itself
            self._unrecorded += 1

    def handleError(self, record: logging.LogRecord) -> None:  # noqa: N802 - the stdlib's name
        self._unrecorded += 1

    def pending(self) -> Counts:
        with self._mu:
            return {day: dict(doc) for day, doc in self._pending.items()}

    def _take(self) -> Counts:
        with self._mu:
            taken, self._pending = self._pending, {}
        return taken

    def _put_back(self, taken: Counts) -> None:
        with self._mu:
            for day, doc in taken.items():
                self._pending[day] = _add(doc, self._pending.get(day, {}))

    async def write_counts(self, docs: Docs) -> Counts:
        """Write what waits, merged into each day's document; returns those documents. Raises
        when the store is down (the counts wait for the next flush)."""
        taken = self._take()
        merged: Counts = {}
        try:
            for day, more in sorted(taken.items()):
                merged[day] = await self._merge(docs, day, more)
        except BaseException:
            # A cancel after a day's transaction committed but before `merged` holds it puts that
            # day back too: it may be counted twice. Fine for counts; never lost.
            self._put_back({d: v for d, v in taken.items() if d not in merged})
            raise
        return merged

    async def _merge(self, docs: Docs, day: str, more: dict[str, Any]) -> dict[str, Any]:
        path = f"{self._coll}/{day}"

        async def fn(tx: DocTx) -> dict[str, Any]:
            new = _add(await tx.get(path) or {}, more)
            tx.set(path, new)
            return new

        return await docs.transaction(fn)

    def day_of(self, now: datetime) -> str:
        return f"{now.astimezone(self._tz):%Y%m%d}"

    async def stored(self, docs: Docs, now: datetime) -> dict[str, Any]:
        """Today's stored document plus what still waits (the counts so far)."""
        day = self.day_of(now)
        return _add(await docs.get(f"{self._coll}/{day}") or {}, self.pending().get(day, {}))

    async def today(self, docs: Docs, now: datetime) -> int:
        doc = await self.stored(docs, now)
        return sum(doc["hours"].values())

    async def sweep(self, docs: Docs, now: datetime) -> int:
        cutoff = f"{now.astimezone(self._tz) - timedelta(days=KEEP_DAYS):%Y%m%d}"
        old = [
            Delete(f"{self._coll}/{d}")
            for d, _ in await docs.query(Query(self._coll))
            if d < cutoff
        ]
        if old:
            await docs.write(old)
        return len(old)


__all__ = ["KEEP_DAYS", "MAX_NAMES", "ErrorCounter", "Piles", "hot_hours", "over", "worst_hour"]
