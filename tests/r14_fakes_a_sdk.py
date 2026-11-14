# tests/r14_fakes_a_sdk.py -- R14 Part A's stand-ins for the Google SDK clients (imported bare:
# `from r14_fakes_a_sdk import ...`). `FakeAdminClient` / `FakeFirestoreClient` answer in the
# shapes the real adapters (`storage/firestore_admin.py`, `storage/firestore_walk.py`) read and
# record every call; nothing here talks to Google or spends anything.
from __future__ import annotations

import copy
from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any

from r14_fakes_a import PROJECT, SNAP, parent_id

from jarvis.storage.docs import Doc


def google_error(name: str, message: str) -> Exception:
    """One of `google.api_core.exceptions` (untyped there), made in a typed way."""
    from google.api_core import exceptions

    made: Exception = getattr(exceptions, name)(message)
    return made


class FakeOp:
    def __init__(self, name: str) -> None:
        self.operation = SimpleNamespace(name=name)

    async def result(self, timeout: float | None = None) -> None:
        return None


class FakeAdminClient:
    """Stands in for `FirestoreAdminAsyncClient`: records every call and answers in its shapes."""

    def __init__(self, *, backups: Sequence[Any] = (), exists: bool = True) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._backups = list(backups)
        self.exists = exists
        self.protection = "DELETE_PROTECTION_DISABLED"
        self.done = True

    async def list_backups(self, *, parent: str) -> Any:
        self.calls.append(("list_backups", parent))
        return SimpleNamespace(backups=self._backups)

    async def list_backup_schedules(self, *, parent: str) -> Any:
        self.calls.append(("list_backup_schedules", parent))
        found = SimpleNamespace(name=f"{parent}/backupSchedules/s")
        return SimpleNamespace(backup_schedules=[found])

    async def restore_database(self, *, request: dict[str, Any]) -> FakeOp:
        self.calls.append(("restore_database", request))
        return FakeOp(f"{request['parent']}/databases/{request['database_id']}/operations/o1")

    async def get_operation(self, *, request: dict[str, Any]) -> Any:
        self.calls.append(("get_operation", request))
        return SimpleNamespace(done=self.done)

    async def get_database(self, *, name: str) -> Any:
        self.calls.append(("get_database", name))
        if not self.exists:
            raise google_error("NotFound", "gone")
        state = SimpleNamespace(name=self.protection)
        return SimpleNamespace(name=name, delete_protection_state=state)

    async def update_database(self, *, request: dict[str, Any]) -> FakeOp:
        self.calls.append(("update_database", request))
        return FakeOp("op-update")

    async def delete_database(self, *, name: str) -> FakeOp:
        self.calls.append(("delete_database", name))
        return FakeOp("op-delete")


def sdk_backup(
    *, database: str = "(default)", state: str = "READY", size: int = 0, count: int = 0
) -> Any:
    stats = SimpleNamespace(size_bytes=size, document_count=count, index_count=0)
    return SimpleNamespace(
        name=f"projects/{PROJECT}/locations/asia-south1/backups/x-{database}",
        database=f"projects/{PROJECT}/databases/{database}",
        state=SimpleNamespace(name=state),
        snapshot_time=SNAP,
        stats=stats,
    )


class _Snap:
    def __init__(self, path: str, data: Doc | None) -> None:
        self.id = path.rsplit("/", 1)[-1]
        self._data = data
        self.exists = data is not None

    def to_dict(self) -> Doc | None:
        return copy.deepcopy(self._data)


class _Ref:
    def __init__(self, client: FakeFirestoreClient, path: str) -> None:
        self._c, self._path = client, path
        self._limit: int | None = None

    def limit(self, n: int) -> _Ref:
        self._limit = n
        return self

    def where(self, **_: Any) -> _Ref:
        return self

    def order_by(self, *_: Any, **__: Any) -> _Ref:
        return self

    async def get(self) -> _Snap:
        self._c.calls.append(("get", self._path))
        return _Snap(self._path, self._c.data.get(self._path))

    async def stream(self) -> Any:
        self._c.calls.append(("stream", self._path))
        depth = self._path.count("/") + 1
        rows = sorted(p for p in self._c.data if p.startswith(self._path + "/"))
        rows = [p for p in rows if p.count("/") == depth][: self._limit]
        for p in rows:
            yield _Snap(p, self._c.data[p])

    def count(self, alias: str = "n") -> Any:
        client, group = self._c, self._path

        class _Agg:
            async def get(self) -> list[list[Any]]:
                client.calls.append(("count", group))
                n = sum(1 for p in client.data if parent_id(p) == group)
                return [[SimpleNamespace(alias=alias, value=n)]]

        return _Agg()


class FakeFirestoreClient:
    """Stands in for `firestore.AsyncClient` on the drill copy: records every call."""

    def __init__(self, data: dict[str, Doc] | None = None) -> None:
        self.data = dict(data or {})
        self.calls: list[tuple[str, str]] = []

    async def collections(self) -> Any:
        self.calls.append(("collections", ""))
        for name in sorted({p.split("/", 1)[0] for p in self.data}):
            yield SimpleNamespace(id=name)

    def collection_group(self, group: str) -> _Ref:
        return _Ref(self, group)

    def collection(self, path: str) -> _Ref:
        return _Ref(self, path)

    def document(self, path: str) -> _Ref:
        return _Ref(self, path)

    def close(self) -> None:
        self.calls.append(("close", ""))


__all__ = ["FakeAdminClient", "FakeFirestoreClient", "FakeOp", "google_error", "sdk_backup"]
