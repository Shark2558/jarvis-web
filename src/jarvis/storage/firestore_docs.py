# src/jarvis/storage/firestore_docs.py
"""Docs on Google Cloud Firestore (Native mode). The ONLY module that imports the SDK.

Auth: Application Default Credentials — on Cloud Run that is the service account, so no key
or secret exists anywhere. With FIRESTORE_EMULATOR_HOST set, the SDK talks to the emulator.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from google.api_core.exceptions import AlreadyExists, Conflict, FailedPrecondition
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from jarvis.storage.docs import (
    Create,
    Delete,
    Doc,
    DocExists,
    Docs,
    DocTx,
    IndexNotReady,
    Op,
    Query,
    T,
    chunks,
)

TX_ATTEMPTS = 10  # contention is rare for one owner; retries are cheap


class _FirestoreTx:
    def __init__(self, client: firestore.AsyncClient, tx: Any) -> None:
        self._c, self._t = client, tx

    async def get(self, path: str) -> Doc | None:
        snap = await self._c.document(path).get(transaction=self._t)
        return snap.to_dict() if snap.exists else None

    def set(self, path: str, data: Doc) -> None:
        self._t.set(self._c.document(path), data)

    def create(self, path: str, data: Doc) -> None:
        self._t.create(self._c.document(path), data)

    def delete(self, path: str) -> None:
        self._t.delete(self._c.document(path))


class FirestoreDocs(Docs):
    def __init__(self, *, project: str | None, database: str = "(default)") -> None:
        self._c = firestore.AsyncClient(project=project, database=database)
        # Transactions are few (approvals, audit appends) and short. Queueing them in-process
        # stops our own requests fighting over Firestore's row locks (bursts hit "Transaction
        # lock timeout" and exhaust retries); Firestore still arbitrates across processes.
        self._tx_lock = asyncio.Lock()

    async def get(self, path: str) -> Doc | None:
        snap = await self._c.document(path).get()
        return snap.to_dict() if snap.exists else None

    async def query(self, q: Query) -> list[tuple[str, Doc]]:
        ref: Any = self._c.collection(q.collection)
        if q.where is not None:
            ref = ref.where(filter=FieldFilter(q.where[0], "==", q.where[1]))
        if q.order_by is not None:
            direction = firestore.Query.DESCENDING if q.descending else firestore.Query.ASCENDING
            ref = ref.order_by(q.order_by, direction=direction)
        if q.limit is not None:
            ref = ref.limit(q.limit)
        try:
            return [(snap.id, snap.to_dict() or {}) async for snap in ref.stream()]
        except FailedPrecondition as exc:  # "The query requires an index…"
            raise IndexNotReady(str(exc)[:300]) from exc

    async def write(self, ops: Sequence[Op]) -> None:
        for chunk in chunks(ops, self.MAX_BATCH):
            batch = self._c.batch()
            for op in chunk:
                ref = self._c.document(op.path)
                if isinstance(op, Delete):
                    batch.delete(ref)
                elif isinstance(op, Create):
                    batch.create(ref, op.data)
                else:
                    batch.set(ref, op.data)
            try:
                await batch.commit()
            except (AlreadyExists, Conflict) as exc:
                raise DocExists(str(exc)[:200]) from exc

    async def transaction(self, fn: Callable[[DocTx], Awaitable[T]]) -> T:
        @firestore.async_transactional
        async def run(tx: Any) -> T:
            return await fn(_FirestoreTx(self._c, tx))

        async with self._tx_lock:
            try:
                result: T = await run(self._c.transaction(max_attempts=TX_ATTEMPTS))
            except (AlreadyExists, Conflict) as exc:
                raise DocExists(str(exc)[:200]) from exc
        return result

    async def close(self) -> None:
        self._c.close()  # type: ignore[no-untyped-call]  # HTTP side only
        api = getattr(self._c, "_firestore_api_internal", None)  # private; SDK pinned <3
        if api is not None:
            try:
                await api.transport.close()
            except Exception:  # noqa: BLE001 — best effort at shutdown
                pass
