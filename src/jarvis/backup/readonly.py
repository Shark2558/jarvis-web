# src/jarvis/backup/readonly.py
"""The read-only view the restore drill's checks get for the LIVE database (docs/plans/
r14-hardening.md D4 "Unable to write live", lock 1). The drill side is read through
`storage/firestore_walk.py`, which has no writer at all.

`read_only(docs)` keeps only the two reads of `jarvis.storage.docs.Docs`: `get(path)` and
`query(q)`. It has no `write`, no `transaction`, no `close`, no `__dict__` and holds no attribute
that is a `Docs`; it is deliberately not a `Docs` subclass, so a type checker refuses it wherever a
writer is wanted, and a slip at run time is an `AttributeError`, never a write. Its slots are
fixed: nothing can be added to it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from jarvis.storage.docs import Doc, Docs, Query

_Get = Callable[[str], Awaitable[Doc | None]]
_Query = Callable[[Query], Awaitable[list[tuple[str, Doc]]]]


class ReadOnly:
    """`backup.ports.ReadOnlyDocs` over any store: get and query only."""

    __slots__ = ("_get", "_query")

    def __init__(self, get: _Get, query: _Query) -> None:
        self._get = get
        self._query = query

    async def get(self, path: str) -> Doc | None:
        return await self._get(path)

    async def query(self, q: Any) -> list[tuple[str, Mapping[str, Any]]]:
        if not isinstance(q, Query):
            raise TypeError("a read-only query takes a storage.docs.Query")
        rows: list[tuple[str, Mapping[str, Any]]] = list(await self._query(q))
        return rows


def read_only(docs: Docs | ReadOnly) -> ReadOnly:
    """The read-only view of `docs` (a view stays the same view)."""
    if isinstance(docs, ReadOnly):
        return docs
    store = docs

    async def get(path: str) -> Doc | None:
        return await store.get(path)

    async def query(q: Query) -> list[tuple[str, Doc]]:
        return await store.query(q)

    return ReadOnly(get, query)


__all__ = ["ReadOnly", "read_only"]
