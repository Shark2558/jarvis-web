# src/jarvis/backup/log.py
"""The restore drill's own log (docs/plans/r14-hardening.md D4, data model): the ONE writer of the
drill's state and results. The checks (`verify`, `walk_checks`, `vault_probe`) never import it
(D4 lock 3, an import test): they hand back plain results and `drill.py` writes them here.

    {prefix}backup_drill/current     DrillState: the phase (idle | restoring | verifying |
                                     cleanup), the run (backup, snapshot time, expected count and
                                     size, the operation, the verifier's cursor, its result), a
                                     manual request and this month's manual drills, the month the
                                     scheduled drill ran, when a drill copy was first seen and
                                     last deleted
    {prefix}backup_drills/{yyyymm}   DrillResult (his month): passed | failed | skipped, a
                                     reason code, the counts, the collections, samples and vault
                                     items compared, whether a vault file opened and the canary
                                     held, the minutes and the rupee estimate; the latest of the
                                     month; 13 months

Counts, ids and reason codes only: no document content, no vault text, no key. A state document
that can't be read fails CLOSED: it reads as a clean-up with this month's drill already had, so
no second restore starts (the clean-up asks Google whether a copy exists and deletes it), and is
logged. The tick's writes are transactions that keep a request he made meanwhile (`save`).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jarvis.logging import get_logger
from jarvis.storage.docs import Delete, Doc, Docs, DocTx, Query, Set

log = get_logger(__name__)

STATE_COLLECTION = "backup_drill"
RESULTS_COLLECTION = "backup_drills"
STATE_ID = "current"
KEEP_MONTHS = 13
Phase = Literal["idle", "restoring", "verifying", "cleanup"]
Outcome = Literal["passed", "failed", "skipped"]
T = TypeVar("T")


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def month_key(at: dt.datetime) -> str:
    return at.strftime("%Y%m")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class DrillResult(_Frozen):
    outcome: Outcome
    reason: str | None = Field(default=None, max_length=40)
    at: dt.datetime
    manual: bool = False
    backup: str | None = Field(default=None, max_length=200)  # the backup's own id
    snapshot_time: dt.datetime | None = None
    expected: int | None = None
    counted: int | None = None
    collections: int = 0
    samples: int = 0
    items: int = 0
    files: int = 0
    vault: str | None = Field(default=None, max_length=40)
    canary_ok: bool = False
    minutes: int = 0
    inr: float | None = None

    @property
    def words(self) -> str:
        """`BackupFacts.drill`: "passed", "failed: <reason>", "skipped: no vault"."""
        if self.outcome == "passed":
            return "passed"
        if self.outcome == "skipped":
            return f"skipped: {(self.reason or 'switched off').replace('_', ' ')}"
        return f"failed: {self.reason or 'unknown'}"


class Run(_Frozen):
    backup: str
    snapshot_time: dt.datetime
    expected: int
    size_bytes: int
    started_at: dt.datetime
    manual: bool = False
    inr: float | None = None
    operation: str | None = None
    polls: int = 0
    errors: int = 0  # checks that raised in a row (a drill ends after 3)
    progress: Mapping[str, Any] = Field(default_factory=dict)  # read only: a new Run to change
    result: DrillResult | None = None


class DrillState(_Frozen):
    phase: Phase = "idle"
    run: Run | None = None
    requested_at: dt.datetime | None = None
    manual_month: str | None = None
    manual_count: int = 0
    auto_month: str | None = None
    copy_seen_at: dt.datetime | None = None
    deleted_at: dt.datetime | None = None
    checked_on: str | None = None
    blocked_since: dt.datetime | None = None  # due but unable to start (no backup, no access)
    updated_at: dt.datetime | None = None


REQUEST_FIELDS = ("requested_at", "manual_month", "manual_count")  # `Drill.request`'s own


def _state_of(doc: Doc | None, month: str) -> DrillState:
    if doc is None:
        return DrillState()
    try:
        return DrillState.model_validate(doc)
    except ValidationError:
        log.error("restore drill state unreadable: a clean-up, and no restore this month")
        return DrillState(phase="cleanup", auto_month=month)


class DrillLog:
    def __init__(
        self,
        docs: Docs,
        *,
        zone: dt.tzinfo,
        prefix: str = "jarvis_",
        clock: Callable[[], dt.datetime] = _now,
    ) -> None:
        self._d = docs
        self._zone = zone
        self._state = f"{prefix}{STATE_COLLECTION}/{STATE_ID}"
        self._results = f"{prefix}{RESULTS_COLLECTION}"
        self._clock = clock

    def month_of(self, at: dt.datetime) -> str:
        """His month (the owner's zone), as the drill's limits count it."""
        return month_key(at.astimezone(self._zone))

    def _doc(self, state: DrillState) -> Doc:
        stamped = state.model_copy(update={"updated_at": self._clock()})
        return stamped.model_dump(mode="json")

    def _read(self, doc: Doc | None) -> DrillState:
        return _state_of(doc, self.month_of(self._clock()))

    async def state(self) -> DrillState:
        return self._read(await self._d.get(self._state))

    async def save(self, state: DrillState, *, request: bool = False) -> DrillState:
        """The tick's write, in one transaction: a request he made meanwhile (`change`) is kept,
        unless this write settles it (`request=True`: started, refused, dropped)."""

        async def run(tx: DocTx) -> DrillState:
            new = state
            if not request:
                now = self._read(await tx.get(self._state))
                new = state.model_copy(update={f: getattr(now, f) for f in REQUEST_FIELDS})
            tx.set(self._state, self._doc(new))
            return new

        return await self._d.transaction(run)

    async def change(self, fn: Callable[[DrillState], tuple[DrillState, T]]) -> T:
        """Read-modify-write in one transaction (a manual request and the tick never race)."""

        async def run(tx: DocTx) -> T:
            new, out = fn(self._read(await tx.get(self._state)))
            tx.set(self._state, self._doc(new))
            return out

        return await self._d.transaction(run)

    async def record(self, result: DrillResult) -> None:
        """The month's result (the latest drill of the month), then the oldest past 13 go."""
        await self._d.write(
            [Set(f"{self._results}/{self.month_of(result.at)}", result.model_dump(mode="json"))]
        )
        months = [m for m, _ in await self.results()]
        old = months[:-KEEP_MONTHS]
        if old:
            await self._d.write([Delete(f"{self._results}/{m}") for m in old])

    async def results(self) -> list[tuple[str, DrillResult]]:
        out: list[tuple[str, DrillResult]] = []
        for month, doc in await self._d.query(Query(self._results)):
            try:
                out.append((month, DrillResult.model_validate(doc)))
            except ValidationError:
                log.error("a restore drill result is unreadable")
        return sorted(out, key=lambda r: r[0])

    async def last_result(self) -> DrillResult | None:
        found = await self.results()
        return found[-1][1] if found else None


__all__ = [
    "KEEP_MONTHS",
    "REQUEST_FIELDS",
    "RESULTS_COLLECTION",
    "STATE_COLLECTION",
    "DrillLog",
    "DrillResult",
    "DrillState",
    "Outcome",
    "Phase",
    "Run",
    "month_key",
]
