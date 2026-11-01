# src/jarvis/storage/docs.py
"""A deliberately tiny document-store port (Layer 7).

Repositories (sessions, approvals, audit) speak only this; `FirestoreDocs` is the single
module that imports the Firestore SDK, and `MemoryDocs` is a faithful in-process twin used by
unit tests. Paths are slash-separated like Firestore's: "coll/doc/subcoll/doc".
"""

from __future__ import annotations

import asyncio
import copy
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

Doc = dict[str, Any]
T = TypeVar("T")


class IndexNotReady(RuntimeError):
    """The query needs a composite index that does not exist (yet). Callers may fall back."""


class DocExists(RuntimeError):
    """A create-only write hit an existing document (append-only data must never be replaced)."""


@dataclass(frozen=True)
class Set:
    path: str
    data: Doc


@dataclass(frozen=True)
class Create:
    """Create-only: the whole transaction fails with DocExists if the document exists."""

    path: str
    data: Doc


@dataclass(frozen=True)
class Delete:
    path: str


Op = Set | Create | Delete


@dataclass(frozen=True)
class Query:
    collection: str
    where: tuple[str, Any] | None = None  # equality only
    order_by: str | None = None
    descending: bool = False
    limit: int | None = None


class DocTx(Protocol):
    """Inside a transaction: all reads before any writes; the function may be retried."""

    async def get(self, path: str) -> Doc | None: ...

    def set(self, path: str, data: Doc) -> None: ...

    def create(self, path: str, data: Doc) -> None: ...

    def delete(self, path: str) -> None: ...


class Docs(ABC):
    MAX_BATCH = 500  # Firestore's limit on writes per commit

    @abstractmethod
    async def get(self, path: str) -> Doc | None: ...

    @abstractmethod
    async def query(self, q: Query) -> list[tuple[str, Doc]]:
        """(doc id, data) for documents directly in `q.collection`."""

    @abstractmethod
    async def write(self, ops: Sequence[Op]) -> None:
        """Apply in order. Atomic per chunk of MAX_BATCH ops; chunks commit in order, so put
        the write that makes the others visible (e.g. a header) last."""

    @abstractmethod
    async def transaction(self, fn: Callable[[DocTx], Awaitable[T]]) -> T: ...

    async def close(self) -> None:
        return None


def chunks(ops: Sequence[Op], size: int) -> list[Sequence[Op]]:
    return [ops[i : i + size] for i in range(0, len(ops), size)]


class _MemoryTx:
    def __init__(self, store: MemoryDocs) -> None:
        self._store = store
        self.ops: list[Op] = []

    async def get(self, path: str) -> Doc | None:
        if self.ops:
            raise RuntimeError("transaction reads must come before writes")
        return await self._store.get(path)

    def set(self, path: str, data: Doc) -> None:
        self.ops.append(Set(path, copy.deepcopy(data)))

    def create(self, path: str, data: Doc) -> None:
        self.ops.append(Create(path, copy.deepcopy(data)))

    def delete(self, path: str) -> None:
        self.ops.append(Delete(path))


class MemoryDocs(Docs):
    """In-process Docs with Firestore-like semantics and read/write counters for tests."""

    def __init__(self, *, strict_indexes: bool = False) -> None:
        self._data: dict[str, Doc] = {}
        self._tx_lock = asyncio.Lock()
        self.strict_indexes = strict_indexes  # emulate a composite index still building
        self.reads = 0
        self.sets = 0
        self.deletes = 0
        self.batch_sizes: list[int] = []
        self.tx_sizes: list[int] = []  # writes per committed transaction (Firestore: ≤ MAX_BATCH)
        self.log: list[Op] = []

    async def get(self, path: str) -> Doc | None:
        self.reads += 1
        d = self._data.get(path)
        return copy.deepcopy(d) if d is not None else None

    async def query(self, q: Query) -> list[tuple[str, Doc]]:
        if self.strict_indexes and q.where is not None and q.order_by is not None:
            raise IndexNotReady(f"composite index missing for {q.collection}")
        depth = q.collection.count("/") + 1
        rows = [
            (path.rsplit("/", 1)[1], d)
            for path, d in self._data.items()
            if path.startswith(q.collection + "/") and path.count("/") == depth
        ]
        if q.where is not None:
            field, value = q.where
            rows = [r for r in rows if r[1].get(field) == value]
        if q.order_by is not None:
            key = q.order_by
            rows = [r for r in rows if key in r[1]]  # Firestore omits docs lacking the field
            rows.sort(key=lambda r: r[1][key], reverse=q.descending)
        else:
            rows.sort(key=lambda r: r[0])
        if q.limit is not None:
            rows = rows[: q.limit]
        self.reads += max(1, len(rows))
        return [(i, copy.deepcopy(d)) for i, d in rows]

    def _apply(self, ops: Sequence[Op]) -> None:
        clash = next((o.path for o in ops if isinstance(o, Create) and o.path in self._data), None)
        if clash is not None:  # all-or-nothing, like a Firestore commit
            raise DocExists(clash)
        for op in ops:
            if isinstance(op, Set | Create):
                self._data[op.path] = copy.deepcopy(op.data)
                self.sets += 1
            else:
                self._data.pop(op.path, None)
                self.deletes += 1
            self.log.append(op)

    async def write(self, ops: Sequence[Op]) -> None:
        for chunk in chunks(ops, self.MAX_BATCH):
            self.batch_sizes.append(len(chunk))
            self._apply(chunk)

    async def transaction(self, fn: Callable[[DocTx], Awaitable[T]]) -> T:
        async with self._tx_lock:  # serialisable: same outcome as Firestore's retry-on-conflict
            tx = _MemoryTx(self)
            result = await fn(tx)
            self._apply(tx.ops)
            self.tx_sizes.append(len(tx.ops))
            return result
