# src/jarvis/backup/ports.py
"""Part A's ports (docs/plans/r14-hardening.md D4), owned by I0 so A, B and Vitals build against
one shape.

- `DRILL_DB` is a constant, never a setting; `drill_target(database, live=...)` is the ONE check
  both drill adapters (`storage/firestore_admin.py`, `storage/firestore_walk.py`) call BEFORE any
  Google call: only `jarvis-drill`, never `(default)` nor the live database id (`Settings` also
  refuses a live database named `jarvis-drill` at start-up: lock 5).
- `ReadOnlyDocs`: get and query only (no `write`, no `transaction`; deliberately not a `Docs`
  subclass). The verifier gets it for BOTH sides, the drill copy and the live database.
- `BackupAdmin`, `DrillWalk`: what the drill needs from Firestore's admin API and from the drill
  copy (counts by `count()` aggregations, a few samples), behind fakes in the tests.
- `BackupFacts` / `BackupStatus`: the backups' facts, read by Part B and the Vitals board. Part A
  is the only producer of the backup kinds and of the database-size item.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Protocol

DRILL_DB: Final = "jarvis-drill"
LIVE_DEFAULT: Final = "(default)"


class LiveTargetRefused(ValueError):
    """A drill adapter was asked to touch a database that is not the drill copy."""


def drill_target(database: str, *, live: str) -> str:
    """`database` if it is the drill copy and not the live database; else `LiveTargetRefused`."""
    if database != DRILL_DB or database in (LIVE_DEFAULT, live):
        raise LiveTargetRefused(
            "only the drill copy may be restored, read for the drill or deleted"
        )
    return database


class ReadOnlyDocs(Protocol):
    """Reads only. `Doc` and `Query` are `jarvis.storage.docs`'s shapes."""

    async def get(self, path: str) -> Mapping[str, Any] | None: ...

    async def query(self, q: Any) -> list[tuple[str, Mapping[str, Any]]]: ...


@dataclass(frozen=True)
class BackupInfo:
    """One backup as Firestore lists it. `size_bytes` / `document_count` stay None until Google
    has filled its stats (empty even while READY): a drill never starts on one of those (A2)."""

    name: str
    database: str
    state: str  # CREATING | READY | NOT_AVAILABLE
    snapshot_time: datetime | None
    size_bytes: int | None = None
    document_count: int | None = None

    @property
    def stats_ready(self) -> bool:
        return (
            self.state == "READY"
            and self.size_bytes is not None
            and self.document_count is not None
            and self.document_count > 0
        )


@dataclass(frozen=True)
class DatabaseInfo:
    database: str
    delete_protection: bool


class BackupAdmin(Protocol):
    """Firestore's admin API, as the drill uses it (every call checks `drill_target` first)."""

    async def list_backups(self) -> Sequence[BackupInfo]: ...

    async def schedules(self) -> Sequence[str]: ...

    async def restore(self, backup: str, database: str) -> str: ...  # the operation's name

    async def operation_done(self, operation: str) -> bool: ...

    async def get_database(self, database: str) -> DatabaseInfo | None: ...

    async def set_delete_protection(self, database: str, on: bool) -> None: ...

    async def delete_database(self, database: str) -> None: ...


class DrillWalk(Protocol):
    """The drill copy, read only: its collection ids, counts and a few samples."""

    async def collections(self) -> Sequence[str]: ...

    async def count(self, collection_group: str) -> int: ...

    async def sample(
        self, collection: str, limit: int
    ) -> Sequence[tuple[str, Mapping[str, Any]]]: ...


@dataclass(frozen=True)
class BackupFacts:
    """What Vitals and Part B may know about the backups (no names of things inside them)."""

    set_up: bool = False  # a schedule was seen once (until then: "not set up", no alerts)
    schedule_seen_at: datetime | None = None
    newest_at: datetime | None = None  # the newest READY backup's snapshot time
    size_bytes: int | None = None
    document_count: int | None = None
    drill: str | None = None  # "passed" | "failed: <reason>" | "skipped: no vault" | None
    drill_at: datetime | None = None


NOT_SET_UP: Final = BackupFacts()


class BackupStatus(Protocol):
    async def facts(self) -> BackupFacts: ...


__all__ = [
    "DRILL_DB",
    "LIVE_DEFAULT",
    "NOT_SET_UP",
    "BackupAdmin",
    "BackupFacts",
    "BackupInfo",
    "BackupStatus",
    "DatabaseInfo",
    "DrillWalk",
    "LiveTargetRefused",
    "ReadOnlyDocs",
    "drill_target",
]
