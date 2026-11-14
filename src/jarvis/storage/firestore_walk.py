# src/jarvis/storage/firestore_walk.py
"""The restore drill's reader of its throw-away copy (docs/plans/r14-hardening.md D4):
`backup.ports.DrillWalk` (its collection ids, `count()` aggregations per collection group, a few
samples) and `backup.ports.ReadOnlyDocs` (get, query) on the database `jarvis-drill` only.

Lock 2: the id is checked with `backup.ports.drill_target` when the reader is made AND again before
every call, so it can never be pointed at `(default)` or the live database. It has no writer:
no `write`, no `transaction`, no batch. Lazy: the SDK is imported at the first call (a test passes
a fake client). A `count()` is billed about one read per 1,000 index entries (S2), so counting the
copy costs about nothing; samples are bounded by the caller.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from jarvis.backup.ports import DRILL_DB, drill_target
from jarvis.storage.docs import Doc, Query

MAX_ID_CHARS = 1500  # Firestore's own limit on a collection id's bytes


def _group_id(collection_group: str) -> str:
    if not collection_group or "/" in collection_group or len(collection_group) > MAX_ID_CHARS:
        raise ValueError("not a collection id")
    return collection_group


class FirestoreWalk:
    """Reads only, on the drill copy."""

    def __init__(
        self, *, project: str | None, live: str, database: str = DRILL_DB, client: Any = None
    ) -> None:
        self._db = drill_target(database, live=live)
        self._live = live
        self._project = project
        self._client = client

    def _c(self) -> Any:
        drill_target(self._db, live=self._live)  # before ANY call
        if self._client is None:
            from google.cloud import firestore

            self._client = firestore.AsyncClient(project=self._project, database=self._db)
        return self._client

    async def collections(self) -> Sequence[str]:
        return [str(c.id) async for c in self._c().collections()]

    async def count(self, collection_group: str) -> int:
        group = _group_id(collection_group)
        got = await self._c().collection_group(group).count(alias="n").get()
        return int(got[0][0].value) if got and got[0] else 0

    async def sample(self, collection: str, limit: int) -> Sequence[tuple[str, Doc]]:
        ref = self._c().collection(collection).limit(max(1, int(limit)))
        return [(snap.id, snap.to_dict() or {}) async for snap in ref.stream()]

    async def get(self, path: str) -> Doc | None:
        snap = await self._c().document(path).get()
        data: Doc | None = snap.to_dict() if snap.exists else None
        return data

    async def query(self, q: Any) -> list[tuple[str, Doc]]:
        if not isinstance(q, Query):
            raise TypeError("a drill query takes a storage.docs.Query")
        ref: Any = self._c().collection(q.collection)
        if q.where is not None:
            from google.cloud.firestore_v1.base_query import FieldFilter

            ref = ref.where(filter=FieldFilter(q.where[0], "==", q.where[1]))
        if q.order_by is not None:
            ref = ref.order_by(q.order_by, direction="DESCENDING" if q.descending else "ASCENDING")
        if q.limit is not None:
            ref = ref.limit(q.limit)
        return [(snap.id, snap.to_dict() or {}) async for snap in ref.stream()]

    async def close(self) -> None:
        if self._client is not None:
            self._client.close()


__all__ = ["MAX_ID_CHARS", "FirestoreWalk"]
