# src/jarvis/storage/firestore_admin.py
"""Firestore's admin API as the restore drill uses it (docs/plans/r14-hardening.md D3, D4):
`backup.ports.BackupAdmin` on the SDK's `FirestoreAdminAsyncClient` (pinned google-cloud-firestore
2.34.1 ships it; the async class keeps a tick from blocking the event loop). Lazy: the SDK is
imported only when the first call is made, and tests pass a fake client.

The drill's locks (D4 lock 2): EVERY call passes `backup.ports.drill_target` first.
- The four calls that name a database to act on (`restore`'s target, `get_database`,
  `set_delete_protection`, `delete_database`) pass THAT id: anything but `jarvis-drill`, and
  `(default)` and the live id, is refused before the call.
- The three reads that name none (`list_backups`, `schedules`, `operation_done`) pass the drill id
  against the live one, so an adapter whose live database IS `jarvis-drill` (a real restore into
  that id) refuses to run at all (lock 5, beside `Settings`'). An operation naming a database must
  name the drill copy; a backup to restore must be one of this project's.
Google's "no permission" (`PermissionDenied`, `Forbidden`: before the owner's one-time step) becomes
Python's own `PermissionError` with fixed words, so the callers never import the SDK; every other
error passes through unchanged (the drill decides); a database that is gone reads as None.
Every call has a deadline (`bounded`): `CALL_S`, or what the morning tick's job has left less
`SPARE_S` (never under `MIN_CALL_S`), so one hung call can't overrun the tick; a call cut off
raises `TimeoutError`. Nothing here logs a document, a name of the owner's or Google's own text.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, TypeVar

from google.api_core.exceptions import Forbidden, NotFound, PermissionDenied

from jarvis.backup.ports import DRILL_DB, BackupInfo, DatabaseInfo, drill_target
from jarvis.ticks import time_left as tick_time_left

PROTECTION_ON = "DELETE_PROTECTION_ENABLED"
PROTECTION_OFF = "DELETE_PROTECTION_DISABLED"
ALL_LOCATIONS = "-"
_OP_DATABASE = re.compile(r"/databases/([^/]+)/")
UPDATE_WAIT_S = 15.0
CALL_S = 20.0  # one Google call at most
SPARE_S = 2.0  # what a call leaves of the tick's time
MIN_CALL_S = 1.0
NO_ACCESS = "JARVIS has no access to the backups yet (the one-time step grants it)"
T = TypeVar("T")
TimeLeft = Callable[[], float | None]


def call_limit(time_left: TimeLeft) -> float:
    """Seconds one Google call may take: `CALL_S`, or less when the tick's job is short."""
    left = time_left()
    if left is None:
        return CALL_S
    return max(MIN_CALL_S, min(CALL_S, left - SPARE_S))


async def bounded(pending: Awaitable[T], time_left: TimeLeft) -> T:
    """One Google call within its deadline; Google's "no permission" as a `PermissionError`."""
    try:
        async with asyncio.timeout(call_limit(time_left)):
            return await pending
    except (PermissionDenied, Forbidden):
        raise PermissionError(NO_ACCESS) from None


def _state(value: Any) -> str:
    name = getattr(value, "name", value)
    return str(name) if name else "STATE_UNSPECIFIED"


def _short(database: str) -> str:
    return database.rsplit("/databases/", 1)[-1]


def _info(raw: Any) -> BackupInfo:
    stats = getattr(raw, "stats", None)
    size = int(getattr(stats, "size_bytes", 0) or 0)
    count = int(getattr(stats, "document_count", 0) or 0)
    return BackupInfo(
        name=str(raw.name),
        database=_short(str(raw.database)),
        state=_state(raw.state),
        snapshot_time=getattr(raw, "snapshot_time", None),
        size_bytes=size or None,  # empty until Google fills them (A2): never 0 for "known"
        document_count=count or None,
    )


class FirestoreAdmin:
    """`backup.ports.BackupAdmin` for one project; `live` is `Settings.firestore_database`."""

    def __init__(
        self, *, project: str, live: str, client: Any = None, time_left: TimeLeft = tick_time_left
    ) -> None:
        drill_target(DRILL_DB, live=live)  # refuse to exist with the drill id as the live one
        self._project = project
        self._live = live
        self._client = client
        self._time_left = time_left

    async def _call(self, pending: Awaitable[T]) -> T:
        return await bounded(pending, self._time_left)

    def _c(self) -> Any:
        if self._client is None:
            from google.cloud.firestore_admin_v1.services.firestore_admin import (
                FirestoreAdminAsyncClient,
            )

            self._client = FirestoreAdminAsyncClient()
        return self._client

    def _sane(self) -> None:
        drill_target(DRILL_DB, live=self._live)

    def _target(self, database: str) -> str:
        return f"projects/{self._project}/databases/{drill_target(database, live=self._live)}"

    async def list_backups(self) -> Sequence[BackupInfo]:
        self._sane()
        parent = f"projects/{self._project}/locations/{ALL_LOCATIONS}"
        got = await self._call(self._c().list_backups(parent=parent))
        found = [_info(b) for b in getattr(got, "backups", ())]
        return [b for b in found if b.database == self._live]

    async def schedules(self) -> Sequence[str]:
        self._sane()
        parent = f"projects/{self._project}/databases/{self._live}"
        got = await self._call(self._c().list_backup_schedules(parent=parent))
        return [str(s.name) for s in getattr(got, "backup_schedules", ())]

    async def restore(self, backup: str, database: str) -> str:
        target = drill_target(database, live=self._live)
        if not backup.startswith(f"projects/{self._project}/locations/") or (
            "/backups/" not in backup
        ):
            raise ValueError("only a backup of this project is restored")
        request = {"parent": f"projects/{self._project}", "database_id": target, "backup": backup}
        op = await self._call(self._c().restore_database(request=request))
        return str(op.operation.name)

    async def operation_done(self, operation: str) -> bool:
        self._sane()
        named = _OP_DATABASE.search(operation)
        if named is not None:
            drill_target(named.group(1), live=self._live)
        got = await self._call(self._c().get_operation(request={"name": operation}))
        return bool(getattr(got, "done", False))

    async def get_database(self, database: str) -> DatabaseInfo | None:
        name = self._target(database)
        try:
            got = await self._call(self._c().get_database(name=name))
        except NotFound:
            return None
        state = _state(getattr(got, "delete_protection_state", None))
        return DatabaseInfo(database, delete_protection=state == PROTECTION_ON)

    async def set_delete_protection(self, database: str, on: bool) -> None:
        name = self._target(database)
        state = PROTECTION_ON if on else PROTECTION_OFF
        request = {
            "database": {"name": name, "delete_protection_state": state},
            "update_mask": {"paths": ["delete_protection_state"]},
        }
        op = await self._call(self._c().update_database(request=request))
        await self._call(op.result(timeout=UPDATE_WAIT_S))

    async def delete_database(self, database: str) -> None:
        """Starts the delete; the drill sees it gone with `get_database` (next tick at latest)."""
        name = self._target(database)
        await self._call(self._c().delete_database(name=name))


__all__ = [
    "CALL_S",
    "MIN_CALL_S",
    "NO_ACCESS",
    "PROTECTION_OFF",
    "PROTECTION_ON",
    "SPARE_S",
    "FirestoreAdmin",
    "bounded",
    "call_limit",
]
