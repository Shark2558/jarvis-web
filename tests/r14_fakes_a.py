# tests/r14_fakes_a.py -- R14 Part A's fakes (imported bare: `from r14_fakes_a import ...`; CI runs
# plain pytest from the repository root, which is not on sys.path). Nothing here talks to Google or
# spends anything: `World` is the live database (a `MemoryDocs`), its daily backups (snapshots of
# the live data) and the throw-away drill copy; `FakeAdmin` / `FakeWalk` are the drill's two ports
# on it; `FakeAdminClient` / `FakeFirestoreClient` stand in for the Google SDK clients the real
# adapters (`storage/firestore_admin.py`, `storage/firestore_walk.py`) call, recording every call.
from __future__ import annotations

import copy
import datetime as dt
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from jarvis.backup.ports import DRILL_DB, BackupInfo, DatabaseInfo, drill_target
from jarvis.keyring import Keyring
from jarvis.notify.ports import Delivery, Signal
from jarvis.storage.docs import Doc, MemoryDocs, Query, Set
from jarvis.vault.crypto import VaultCrypto
from jarvis.vault.models import FileRef, Item, VaultIndex
from jarvis.vault.store import VaultStore

PREFIX = "jarvis_"
UID = "owner-1"
GIB = 1024**3
SNAP = dt.datetime(2026, 11, 14, 3, 0, tzinfo=dt.UTC)  # the backup's point in time
RESTAMP_FIELD = "__update_time__"  # Firestore's own update_time (a reserved `__x__` name)
ROOT_KEY = bytes(range(1, 33))
OTHER_KEY = bytes(range(101, 133))
PROJECT = "proj-example"
BACKUP_NAME = f"projects/{PROJECT}/locations/asia-south1/backups/b1"


def ring(key: bytes = ROOT_KEY) -> Keyring:
    return Keyring(key)


def _parent_id(path: str) -> str:
    parts = path.split("/")
    return parts[-2] if len(parts) >= 2 else ""


def data_of(docs: MemoryDocs) -> dict[str, Doc]:
    """Every document of a MemoryDocs (a test twin: its store is read directly)."""
    return copy.deepcopy(docs._data)  # noqa: SLF001 - the fake's own twin


class FakeConflict(RuntimeError):
    """The drill id is taken (Google: AlreadyExists)."""


class FakeDenied(PermissionError):
    """Google refused (the adapter's PermissionError), e.g. before the owner's one-time step."""


@dataclass
class World:
    """The live database, its backups and the drill copy, all in memory."""

    live: MemoryDocs = field(default_factory=MemoryDocs)
    backups: list[BackupInfo] = field(default_factory=list)
    snapshots: dict[str, dict[str, Doc]] = field(default_factory=dict)
    schedules: list[str] = field(default_factory=list)
    drill: MemoryDocs | None = None
    drill_protection: bool = False
    restore_polls: int = 1  # polls until the restore is done
    restamp: bool = False  # a restore stamps a new update_time on every document
    drop_on_restore: tuple[str, ...] = ()  # paths a broken restore leaves out
    tamper_on_restore: dict[str, Doc] = field(default_factory=dict)
    restore_fails: bool = False  # the operation ends without a database
    delete_fails: bool = False  # Google refuses the delete (the condition not honoured)
    denied: bool = False  # no backup permission yet (before the set-up)
    polls: int = 0

    def snapshot(self, name: str = BACKUP_NAME, *, at: dt.datetime = SNAP, **kw: Any) -> None:
        data = data_of(self.live)
        for path, doc in data.items():
            doc.setdefault(RESTAMP_FIELD, "2026-11-13T10:00:00+00:00")
            self.live._data[path][RESTAMP_FIELD] = doc[RESTAMP_FIELD]  # noqa: SLF001
        self.snapshots[name] = data
        stats = {"size_bytes": 100 * 1024 * 1024, "document_count": len(data), **kw}
        self.backups.append(
            BackupInfo(name=name, database="(default)", state="READY", snapshot_time=at, **stats)
        )
        if not self.schedules:
            self.schedules.append(f"projects/{PROJECT}/databases/(default)/backupSchedules/s1")

    def restore_into_drill(self, backup: str) -> None:
        data = copy.deepcopy(self.snapshots[backup])
        for path in self.drop_on_restore:
            data.pop(path, None)
        data.update(copy.deepcopy(self.tamper_on_restore))
        if self.restamp:
            for doc in data.values():
                doc[RESTAMP_FIELD] = "2026-11-15T05:00:00+00:00"
        drill = MemoryDocs()
        drill._data.update(data)  # noqa: SLF001 - the fake's own twin
        self.drill = drill


class FakeAdmin:
    """`backup.ports.BackupAdmin` on a `World`; every database call checks `drill_target`."""

    def __init__(self, world: World, *, live: str = "(default)") -> None:
        self.w, self.live = world, live
        self.calls: list[tuple[str, ...]] = []

    def _check(self, name: str, database: str | None = None) -> None:
        if database is not None:
            drill_target(database, live=self.live)
        self.calls.append((name, *(() if database is None else (database,))))
        if self.w.denied:
            raise FakeDenied(name)

    async def list_backups(self) -> Sequence[BackupInfo]:
        self._check("list_backups")
        return list(self.w.backups)

    async def schedules(self) -> Sequence[str]:
        self._check("schedules")
        return list(self.w.schedules)

    async def restore(self, backup: str, database: str) -> str:
        self._check("restore", database)
        if self.w.drill is not None:
            raise FakeConflict(database)
        self.w.polls = 0
        if not self.w.restore_fails:
            self.w.restore_into_drill(backup)
        return f"projects/{PROJECT}/databases/{database}/operations/op1"

    async def operation_done(self, operation: str) -> bool:
        self._check("operation_done")
        self.w.polls += 1
        return self.w.polls >= self.w.restore_polls

    async def get_database(self, database: str) -> DatabaseInfo | None:
        self._check("get_database", database)
        if self.w.drill is None:
            return None
        return DatabaseInfo(database, self.w.drill_protection)

    async def set_delete_protection(self, database: str, on: bool) -> None:
        self._check("set_delete_protection", database)
        self.w.drill_protection = on

    async def delete_database(self, database: str) -> None:
        self._check("delete_database", database)
        if self.w.drill_protection:
            raise RuntimeError("delete protection is on")
        if self.w.delete_fails:
            raise FakeDenied("delete")
        self.w.drill = None

    def names(self) -> list[str]:
        return [c[0] for c in self.calls]


class FakeWalk:
    """`DrillWalk` + `ReadOnlyDocs` on the drill copy (reads only; no write)."""

    def __init__(self, world: World, database: str = DRILL_DB, *, live: str = "(default)") -> None:
        self.w = world
        self.database = drill_target(database, live=live)
        self.reads = 0

    def _docs(self) -> MemoryDocs:
        if self.w.drill is None:
            raise RuntimeError("no drill copy")
        return self.w.drill

    async def collections(self) -> Sequence[str]:
        return sorted({p.split("/", 1)[0] for p in data_of(self._docs())})

    async def count(self, collection_group: str) -> int:
        self.reads += 1
        return sum(1 for p in data_of(self._docs()) if _parent_id(p) == collection_group)

    async def sample(self, collection: str, limit: int) -> Sequence[tuple[str, Doc]]:
        return await self._docs().query(Query(collection, limit=limit))

    async def get(self, path: str) -> Doc | None:
        return await self._docs().get(path)

    async def query(self, q: Any) -> list[tuple[str, Doc]]:
        return await self._docs().query(q)


class RecordingNotifier:
    """The app's notifier, recording what would be sent (fixed templates only)."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, Signal, str]] = []

    async def notify(
        self,
        uid: str,
        signal: Signal,
        message: str,
        *,
        named_message: str | None = None,
        photo: bytes | None = None,
    ) -> Delivery:
        self.sent.append((uid, signal, message))
        return Delivery(action="ring", reason="test", telegram=True)

    def kinds(self) -> list[tuple[str, str | None]]:
        return [(s.kind, s.subject) for _, s, _ in self.sent]


# ---- the live data a drill checks ------------------------------------------------------------


async def seed_vault(live: MemoryDocs, keys: Keyring, uid: str = UID) -> str:
    """One vault item with one sealed file, written through the vault store's own path."""
    crypto = VaultCrypto(keys)
    store = VaultStore(live, crypto, prefix=PREFIX, clock=lambda: SNAP - dt.timedelta(days=2))
    item_id, fid = "v_0123456789ab", "f_0123456789ab"
    data = b"made-up passport scan " * 30_000  # about 660 KB: two chunks of 512 KiB
    wrapped, blobs = crypto.seal(uid, item_id, fid, data)
    await store.put_chunks(uid, fid, blobs)
    at = SNAP - dt.timedelta(days=2)
    ref = FileRef(
        fid=fid,
        mime="application/pdf",
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        chunks=len(blobs),
        dek=wrapped,
        added_at=at,
    )
    item = Item(
        id=item_id, type="passport", title="Passport", files=(ref,), created_at=at, updated_at=at
    )
    await store.change(uid, lambda i: (VaultIndex(items=(item,)), None))
    return item_id


async def seed_rest(live: MemoryDocs, uid: str = UID) -> None:
    """A few ordinary documents, a sub-collection, an activity day and a deleted-items bin."""
    at = (SNAP - dt.timedelta(hours=5)).isoformat()
    ops = [
        Set(f"{PREFIX}sessions/s1", {"user_id": uid, "updated_at": at, "title": "A chat"}),
        Set(f"{PREFIX}sessions/s1/turns/000001", {"role": "user", "at": at, "text": "hello"}),
        Set(f"{PREFIX}notes/n1", {"user_id": uid, "updated_at": at, "blob": "sealed"}),
        Set(f"{PREFIX}activity_days/{uid}/days/20261113", {"day": "20261113"}),
        Set(f"{PREFIX}activity/{uid}/d20261113/a1", {"at": at, "what": "chat"}),
        Set(f"{PREFIX}deleted_items/{uid}/items/u1", {"at": at, "kind": "note"}),
        Set(f"{PREFIX}settings/{uid}", {"updated_at": at, "wit": "film"}),
    ]
    await live.write(ops)


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
            from google.api_core.exceptions import NotFound

            raise NotFound("gone")
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
                n = sum(1 for p in client.data if _parent_id(p) == group)
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


__all__ = [
    "BACKUP_NAME",
    "GIB",
    "OTHER_KEY",
    "PREFIX",
    "PROJECT",
    "RESTAMP_FIELD",
    "ROOT_KEY",
    "SNAP",
    "UID",
    "FakeAdmin",
    "FakeAdminClient",
    "FakeConflict",
    "FakeDenied",
    "FakeFirestoreClient",
    "FakeOp",
    "FakeWalk",
    "RecordingNotifier",
    "World",
    "data_of",
    "ring",
    "sdk_backup",
    "seed_rest",
    "seed_vault",
]
