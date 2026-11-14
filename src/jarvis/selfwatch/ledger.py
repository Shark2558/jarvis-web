# src/jarvis/selfwatch/ledger.py
"""Part B's two ledgers (docs/plans/r14-hardening.md D5, review A6).

- `JobLedger`: every tick and watchdog job's (and sweep's) failed or timed-out runs in a row, fed
  by the tick observer (`ticks.JobOutcome`). `ok` ends a streak; a skip (the clock had no time
  left for the job) never counts and never ends one. A streak is told once (`mark_told`); the
  job that reports never reports its own streak (`exclude`). Kept in memory and written, only
  when it changed, to `{prefix}selfwatch/jobs` by the 5-minute job (batched): names, counts and
  times only. What this process saw wins over the stored copy (a restart reads it back once).
- `Told`: the once-only claims, `{prefix}selfwatch_told/{uid}_{hash}` with the kind and the time
  (the cause is hashed, never kept), written BEFORE the alert is sent, so a failed or slow send
  can never be repeated in a loop. With the store down a claim is kept in this process only.
  Swept after 30 days.

No message text, no logger name and no exception text is ever kept here.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from jarvis.logging import get_logger
from jarvis.storage.docs import Delete, DocExists, Docs, DocTx, Query, Set
from jarvis.undo.store import owner_ok

log = get_logger(__name__)

# The outcomes that count toward a streak (A6: a skip for time never does).
FAILING: frozenset[str] = frozenset({"failed", "timed_out"})
MAX_JOBS = 200  # job names come from the code; the table can't grow without bound
_NAME = re.compile(r"[A-Za-z0-9_.-]{1,64}")
TOLD_KEEP = timedelta(days=30)
MAX_MEMORY_CLAIMS = 500


@dataclass(frozen=True)
class Streak:
    runs: int  # failed or timed-out runs in a row
    since: datetime  # the first of them
    told_at: datetime | None = None


def step(entry: Streak | None, outcome: str, at: datetime) -> Streak | None:
    """The streak after one more outcome: a failure adds one, ok ends it, a skip changes nothing."""
    if outcome in FAILING:
        return Streak(1, at) if entry is None else replace(entry, runs=entry.runs + 1)
    if outcome == "ok":
        return None
    return entry


def new_in_streak(failing: Sequence[tuple[str, Streak]]) -> list[str]:
    """The failing jobs not told yet (once per streak)."""
    return [name for name, s in failing if s.told_at is None]


def _iso(at: datetime | None) -> str | None:
    return None if at is None else at.isoformat()


def _when(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _decode(raw: object) -> Streak | None:
    if not isinstance(raw, dict):
        return None
    runs, since = raw.get("runs"), _when(raw.get("since"))
    if not isinstance(runs, int) or isinstance(runs, bool) or runs < 1 or since is None:
        return None
    return Streak(runs, since, _when(raw.get("told_at")))


class JobLedger:
    """Streaks by job name, in memory first (the observer is synchronous and never waits)."""

    def __init__(self, *, prefix: str = "jarvis_") -> None:
        self._path = f"{prefix}selfwatch/jobs"
        self._streaks: dict[str, Streak] = {}
        self._seen: set[str] = set()  # names this process has an outcome for
        self._recovered = False  # a told streak ended since the last `take_recovered`
        self.last_alert: datetime | None = None  # the last aggregated `job_failing`
        self.dirty = False
        self.loaded = False

    def observe(self, name: str, outcome: str, at: datetime) -> None:
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            return
        if name not in self._seen and len(self._seen) >= MAX_JOBS:
            return
        self._seen.add(name)
        before = self._streaks.get(name)
        after = step(before, outcome, at)
        if after == before:
            return
        if after is None:
            del self._streaks[name]
            self._recovered = self._recovered or (before is not None and before.told_at is not None)
        else:
            self._streaks[name] = after
        self.dirty = True

    def failing(self, threshold: int, exclude: str = "") -> list[tuple[str, Streak]]:
        """Jobs with at least `threshold` failed runs in a row, by name; never `exclude`."""
        return sorted(
            (n, s) for n, s in self._streaks.items() if s.runs >= threshold and n != exclude
        )

    def untold(self, threshold: int, exclude: str = "") -> list[str]:
        return new_in_streak(self.failing(threshold, exclude))

    def mark_told(self, names: Sequence[str], at: datetime) -> None:
        for name in names:
            s = self._streaks.get(name)
            if s is not None and s.told_at is None:
                self._streaks[name] = replace(s, told_at=at)
                self.dirty = True

    def has_told(self) -> bool:
        """Whether a streak that was told is still going (its alert is still true)."""
        return any(s.told_at is not None for s in self._streaks.values())

    def take_recovered(self) -> bool:
        """True once when every told streak has ended."""
        if not self._recovered or self.has_told():
            return False
        self._recovered = False
        self.dirty = True
        return True

    def _doc(self) -> dict[str, Any]:
        jobs = {
            n: {"runs": s.runs, "since": _iso(s.since), "told_at": _iso(s.told_at)}
            for n, s in self._streaks.items()
        }
        return {"jobs": jobs, "last_alert": _iso(self.last_alert), "recovered": self._recovered}

    async def flush(self, docs: Docs) -> bool:
        """Write the ledger when it changed. Raises when the store is down (kept dirty)."""
        if not self.dirty:
            return False
        await docs.write([Set(self._path, self._doc())])
        self.dirty = False
        return True

    async def load(self, docs: Docs) -> None:
        """Read the stored ledger once (after a restart); this process's own outcomes win."""
        if self.loaded:
            return
        try:
            doc = await docs.get(self._path)
        except Exception as exc:  # noqa: BLE001 - the watch runs on what it saw
            log.warning("selfwatch ledger unreadable", extra={"error": type(exc).__name__})
            return
        self.loaded = True
        self._merge(doc or {})

    def _merge(self, doc: dict[str, Any]) -> None:
        jobs = doc.get("jobs")
        for name, raw in (jobs if isinstance(jobs, dict) else {}).items():
            got = _decode(raw)
            if got is not None and name not in self._seen and _NAME.fullmatch(str(name)):
                if len(self._streaks) < MAX_JOBS:
                    self._streaks[str(name)] = got
        self.last_alert = self.last_alert or _when(doc.get("last_alert"))
        self._recovered = self._recovered or doc.get("recovered") is True


class Told:
    """Once-only claims per owner, kind and cause (D5: written before the send)."""

    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self._docs = docs
        self._coll = f"{prefix}selfwatch_told"
        self._memory: dict[str, datetime] = {}

    @staticmethod
    def key(uid: str, kind: str, cause: str) -> str:
        digest = hashlib.sha256(f"{kind}|{cause}".encode()).hexdigest()[:24]
        return f"{uid}_{digest}"

    def _remember(self, key: str, now: datetime) -> None:
        if len(self._memory) >= MAX_MEMORY_CLAIMS:
            for old in sorted(self._memory, key=self._memory.__getitem__)[: MAX_MEMORY_CLAIMS // 2]:
                del self._memory[old]
        self._memory[key] = now

    async def claim(self, uid: str, kind: str, cause: str, now: datetime) -> bool:
        """True when this call made the claim (tell now); False when it was made before."""
        if not owner_ok(uid):
            return False
        key = self.key(uid, kind, cause)
        if key in self._memory:
            return False
        path = f"{self._coll}/{key}"

        async def run(tx: DocTx) -> bool:
            if await tx.get(path) is not None:
                return False
            tx.create(path, {"uid": uid, "kind": kind, "at": now.isoformat()})
            return True

        try:
            made = await self._docs.transaction(run)
        except DocExists:
            made = False
        except Exception as exc:  # noqa: BLE001 - the store is down: claim in this process only
            log.warning("selfwatch claim kept in memory", extra={"error": type(exc).__name__})
            made = True
        self._remember(key, now)
        return made

    async def count(self, uid: str) -> int:
        return len(await self._docs.query(Query(self._coll, where=("uid", uid))))

    async def sweep(self, now: datetime) -> int:
        """Delete the claims older than 30 days. Returns how many."""
        cutoff = now - TOLD_KEEP
        old = [
            Delete(f"{self._coll}/{key}")
            for key, doc in await self._docs.query(Query(self._coll))
            if (at := _when(doc.get("at"))) is None or at < cutoff
        ]
        if old:
            await self._docs.write(old)
        return len(old)


__all__ = [
    "FAILING",
    "MAX_JOBS",
    "TOLD_KEEP",
    "JobLedger",
    "Streak",
    "Told",
    "new_in_streak",
    "step",
]
