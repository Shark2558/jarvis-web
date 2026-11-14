# tests/r14_fakes.py -- R14 I0's shared fakes (imported bare: `from r14_fakes import ...`; CI runs
# plain pytest from the repository root, which is not on sys.path). Each part has its own file
# (`r14_fakes_a.py` ... `r14_fakes_d.py`); nothing here talks to Google or spends anything.
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from jarvis.backup.ports import BackupFacts, BackupInfo
from jarvis.llm.base import ToolSpec
from jarvis.ticks import JobOutcome


def fake_spec(name: str) -> ToolSpec:
    return ToolSpec(name=name, description=f"the {name} tool", input_schema={"type": "object"})


class RecordingJob:
    """A tick job that records the owners it was given (and, when shared, the order it ran in)."""

    def __init__(self, name: str, *, budget_s: float = 5.0, order: list[str] | None = None) -> None:
        self.name, self.budget_s = name, budget_s
        self.owners: list[tuple[str, ...]] = []
        self.order = order
        self.last: dict[str, int] = {}

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        self.owners.append(tuple(owners))
        if self.order is not None:
            self.order.append(self.name)
        return {"done": 1}


@dataclass
class Outcomes:
    """A tick observer that keeps what it heard (`ticks.TickObserver`)."""

    seen: list[JobOutcome] = field(default_factory=list)

    def __call__(self, outcome: JobOutcome) -> None:
        self.seen.append(outcome)

    def names(self, clock: str | None = None) -> list[str]:
        return [o.name for o in self.seen if clock is None or o.clock == clock]


@dataclass
class FakeBackupStatus:
    """`backup.ports.BackupStatus` with fixed facts (Part B and Vitals read it)."""

    facts_now: BackupFacts = field(default_factory=BackupFacts)

    async def facts(self) -> BackupFacts:
        return self.facts_now


def ready_backup(
    *, size_bytes: int | None = 100 * 1024 * 1024, count: int | None = 35_000
) -> BackupInfo:
    """A READY backup as Firestore lists it; `size_bytes` / `count` None = stats not filled yet."""
    return BackupInfo(
        name="projects/p/locations/asia-south1/backups/b1",
        database="(default)",
        state="READY",
        snapshot_time=datetime(2026, 11, 14, 3, 0, tzinfo=UTC),
        size_bytes=size_bytes,
        document_count=count,
    )


def facts(**kw: Any) -> BackupFacts:
    return BackupFacts(**kw)


__all__ = ["FakeBackupStatus", "Outcomes", "RecordingJob", "facts", "fake_spec", "ready_backup"]
