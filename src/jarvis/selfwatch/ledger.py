# src/jarvis/selfwatch/ledger.py
"""Part B's two ledgers (docs/plans/r14-hardening.md D5, review A6).

- `JobLedger`: every tick and watchdog job's (and sweep's) failed or timed-out runs in a row, fed
  by the tick observer (`ticks.JobOutcome`). `ok` ends a streak; a skip (the clock had no time
  left for the job) never counts and never ends one. A streak is told once (`mark_told`); the
  job that reports never reports its own streak (`exclude`). Kept in memory and written, only
  when it changed, to `{prefix}selfwatch/jobs` by the 5-minute job (batched): names, counts and
  times only. A restart reads it back once: failures seen before that join the stored streak;
  only an `ok` seen here ends it. It is never written before the stored copy was read.
- `Told`: the once-only claims, `{prefix}selfwatch_told/{uid}_{hash}` with the kind and the time
  (the cause is hashed, never kept), written BEFORE the alert is sent, so a slow send can never
  be repeated in a loop. A send that reached nobody gives its claim back (`release`; the teller
  bounds the retries). With the store down a claim is kept in this process only. Swept after 30
  days.

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
    """A stored time, or None: never a naive one (it could not be compared with now)."""
    if not isinstance(value, str):
        return None
    try:
        at = datetime.fromisoformat(value)
    except ValueError:
        return None
    return at if at.tzinfo is not None else None


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
        self._ended: set[str] = set()  # names this process saw `ok` for (a stored streak ended)
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
        if outcome == "ok":
            self._ended.add(name)
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
        """Write the ledger when it changed, never over a stored copy it has not read (False: it
        could not be read). Raises when the write fails (kept dirty). A change the other job's
        observer makes during the write stays dirty for the next one."""
        if not self.dirty:
            return False
        if not self.loaded:
            await self.load(docs)
            if not self.loaded:
                return False
        doc, self.dirty = self._doc(), False
        try:
            await docs.write([Set(self._path, doc)])
        except BaseException:
            self.dirty = True
            raise
        return True

    async def load(self, docs: Docs) -> None:
        """Read the stored ledger once (after a restart) and join what this process saw."""
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
        """The stored streaks joined with this process's: an `ok` seen here ended a stored one;
        failures seen here before the load add to it (its start and its `told_at` kept)."""
        jobs = doc.get("jobs")
        for name, raw in (jobs if isinstance(jobs, dict) else {}).items():
            got = _decode(raw)
            if got is None or name in self._ended or not _NAME.fullmatch(str(name)):
                continue
            mine = self._streaks.get(name)
            if mine is not None:
                told = got.told_at or mine.told_at
                self._streaks[name] = Streak(got.runs + mine.runs, min(got.since, mine.since), told)
            elif len(self._streaks) < MAX_JOBS:
                self._streaks[str(name)] = got
        self.last_alert = self.last_alert or _when(doc.get("last_alert"))
        self._recovered = self._recovered or doc.get("recovered") is True


class Told:
    """Once-only claims per owner, kind and cause (D5: written before the send)."""

    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self._docs = docs
        self._coll = f"{prefix}selfwatch_told"
        self._memory: dict[str, datetime] = {}
        self._released: set[str] = set()  # given back here, but its stored copy may remain

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
        self._remember(key, now)  # before the await: a second claim meanwhile is not made
        path, again = f"{self._coll}/{key}", key in self._released
        body = {"uid": uid, "kind": kind, "at": now.isoformat()}

        async def run(tx: DocTx) -> bool:
            if again:  # given back here: its stored copy (a delete that failed) is ours
                tx.set(path, body)
                return True
            if await tx.get(path) is not None:
                return False
            tx.create(path, body)
            return True

        try:
            made = await self._docs.transaction(run)
        except DocExists:
            made = False
        except Exception as exc:  # noqa: BLE001 - the store is down: claim in this process only
            log.warning("selfwatch claim kept in memory", extra={"error": type(exc).__name__})
            made = True
        except BaseException:
            self._memory.pop(key, None)
            raise
        self._released.discard(key)
        return made

    def forget(self, uid: str, kind: str, cause: str) -> None:
        """Give the claim back in this process (synchronous: safe while being cancelled)."""
        key = self.key(uid, kind, cause)
        self._memory.pop(key, None)
        if len(self._released) < MAX_MEMORY_CLAIMS:
            self._released.add(key)

    async def release(self, uid: str, kind: str, cause: str) -> None:
        """Give the claim back (its send reached nobody): here, and in the store when it can."""
        self.forget(uid, kind, cause)
        key = self.key(uid, kind, cause)
        try:
            await self._docs.write([Delete(f"{self._coll}/{key}")])
        except Exception as exc:  # noqa: BLE001 - given back here; the store's copy is overwritten
            log.warning("selfwatch claim not given back", extra={"error": type(exc).__name__})
            return
        self._released.discard(key)

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
