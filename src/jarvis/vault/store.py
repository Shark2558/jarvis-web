# src/jarvis/vault/store.py
"""The vault on the Docs port (R2 D1, Data model; Layer 7).

    {prefix}vault/{uid}                       {rev, v, kid, blob, bytes_total, updated_at}
    {prefix}vault/{uid}/vault_chunks/{fid}_{nn}  {blob, n, of, at}

`blob` is the whole `VaultIndex` sealed under `vault_index`. A file exists only once its index
entry is written (header last). No query ever reads chunk documents: they are read, written and
deleted by path from the index. Every read of the index fails closed: a document that cannot be
decrypted or parsed raises `VaultUnavailable` and is never overwritten. The decrypted index is
cached per `rev` for at most four owners; chunks are never cached.
"""

from __future__ import annotations

import datetime as dt
from collections import OrderedDict
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import ValidationError

from jarvis.integrations.vault import VaultError
from jarvis.logging import get_logger
from jarvis.storage.docs import Delete, Docs, DocTx, Set
from jarvis.vault.crypto import VaultCrypto
from jarvis.vault.models import (
    PENDING_TTL_S,
    Orphan,
    VaultIndex,
    VaultRejected,
    VaultUnavailable,
)

log = get_logger(__name__)
T = TypeVar("T")
WRITE_GROUP = 6  # chunks per commit (about 4.2 MB, under the 10 MiB request limit)
MAX_BLOB_CHARS = 1_000_000
CACHE_OWNERS = 4
DELETE_GROUP = 200


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class VaultStore:
    def __init__(
        self,
        docs: Docs,
        crypto: VaultCrypto,
        *,
        prefix: str = "jarvis_",
        clock: Callable[[], dt.datetime] = _now,
    ) -> None:
        self._d = docs
        self._c = crypto
        self._col = f"{prefix}vault"
        self._clock = clock
        self._cache: OrderedDict[str, tuple[int, str, VaultIndex]] = OrderedDict()

    def _path(self, uid: str) -> str:
        return f"{self._col}/{uid}"

    def _chunk_path(self, uid: str, fid: str, n: int) -> str:
        return f"{self._col}/{uid}/vault_chunks/{fid}_{n:02d}"

    # ---- the index -------------------------------------------------------------------------

    def _decode(self, uid: str, doc: dict[str, Any] | None) -> tuple[int, VaultIndex]:
        if doc is None:
            return 0, VaultIndex()
        rev = doc.get("rev")
        blob = doc.get("blob")
        if not isinstance(rev, int) or isinstance(rev, bool) or not isinstance(blob, str):
            raise VaultUnavailable("the vault index is unreadable")
        cached = self._cache.get(uid)
        if cached is not None and cached[0] == rev and cached[1] == blob:
            self._cache.move_to_end(uid)
            return rev, cached[2]
        try:
            index = VaultIndex.model_validate_json(self._c.open_index(uid, blob))
        except (VaultError, ValidationError, ValueError) as exc:
            log.error("vault index unreadable", extra={"error": type(exc).__name__})
            raise VaultUnavailable("the vault index is unreadable") from None
        self._remember(uid, rev, blob, index)
        return rev, index

    def _remember(self, uid: str, rev: int, blob: str, index: VaultIndex) -> None:
        self._cache[uid] = (rev, blob, index)
        self._cache.move_to_end(uid)
        while len(self._cache) > CACHE_OWNERS:
            self._cache.popitem(last=False)

    async def load(self, uid: str) -> tuple[int, VaultIndex]:
        """(rev, index); an owner with no vault yet is (0, empty). Raises VaultUnavailable."""
        try:
            doc = await self._d.get(self._path(uid))
        except Exception as exc:  # noqa: BLE001 - any storage failure fails closed
            raise VaultUnavailable("vault storage is unavailable") from exc
        return self._decode(uid, doc)

    async def change(self, uid: str, fn: Callable[[VaultIndex], tuple[VaultIndex, T]]) -> T:
        """Read-modify-write in one transaction. `fn` is pure (it may run more than once) and may
        raise VaultRejected to stop. The index is never replaced if it could not be read."""
        path = self._path(uid)
        out: list[tuple[int, str, VaultIndex]] = []

        async def run(tx: DocTx) -> T:
            rev, index = self._decode(uid, await tx.get(path))
            new, result = fn(index)
            blob = self._c.seal_index(uid, new.model_dump_json().encode())
            if len(blob) > MAX_BLOB_CHARS:
                raise VaultRejected(
                    "vault_full", "The vault has no room for more details.", status=409
                )
            tx.set(
                path,
                {
                    "rev": rev + 1,
                    "v": 1,
                    "kid": self._c.ring.kid,
                    "blob": blob,
                    "bytes_total": new.bytes_total(),
                    "updated_at": self._clock().isoformat(),
                },
            )
            out.append((rev + 1, blob, new))
            return result

        try:
            result = await self._d.transaction(run)
        except (VaultRejected, VaultUnavailable):
            raise
        except Exception as exc:  # noqa: BLE001
            log.error("vault write failed", extra={"error": type(exc).__name__})
            raise VaultUnavailable("vault storage is unavailable") from None
        if out:
            self._remember(uid, *out[-1])
        return result

    # ---- chunks (by path only) -----------------------------------------------------------------

    async def put_chunks(self, uid: str, fid: str, blobs: list[str]) -> None:
        """Commits of at most six chunks. The caller writes the index entry afterwards."""
        at = self._clock().isoformat()
        total = len(blobs)
        try:
            for start in range(0, total, WRITE_GROUP):
                ops = [
                    Set(
                        self._chunk_path(uid, fid, n),
                        {"blob": blobs[n], "n": n, "of": total, "at": at},
                    )
                    for n in range(start, min(total, start + WRITE_GROUP))
                ]
                await self._d.write(ops)
        except Exception as exc:  # noqa: BLE001
            log.error("vault chunk write failed", extra={"error": type(exc).__name__})
            raise VaultUnavailable("vault storage is unavailable") from None

    async def chunk(self, uid: str, fid: str, n: int) -> str:
        try:
            doc = await self._d.get(self._chunk_path(uid, fid, n))
        except Exception as exc:  # noqa: BLE001
            raise VaultUnavailable("vault storage is unavailable") from exc
        blob = (doc or {}).get("blob")
        if not isinstance(blob, str):
            raise VaultUnavailable("a part of the file is missing")
        return blob

    async def drop_chunks(self, uid: str, fid: str, count: int) -> None:
        """Delete a file's chunk documents by path (safe to repeat)."""
        paths = [self._chunk_path(uid, fid, n) for n in range(count)]
        for start in range(0, len(paths), DELETE_GROUP):
            await self._d.write([Delete(p) for p in paths[start : start + DELETE_GROUP]])

    async def sweep(self, uid: str) -> int:
        """Delete the chunks of uploads that never finished (pending > 1 h) and of earlier purges
        whose deletes failed (orphans). Returns how many files' chunks went. Never raises."""
        try:
            now = self._clock()

            def stale(index: VaultIndex) -> tuple[VaultIndex, tuple[Orphan, ...]]:
                old = [
                    p for p in index.pending if (now - p.started_at).total_seconds() > PENDING_TTL_S
                ]
                if not old and not index.orphans:
                    return index, ()
                keep = tuple(p for p in index.pending if p not in old)
                orphans = (*index.orphans, *(Orphan(fid=p.fid, chunks=p.chunks) for p in old))
                return index.model_copy(update={"pending": keep, "orphans": orphans}), orphans

            _, index = await self.load(uid)
            if not index.orphans and not any(
                (now - p.started_at).total_seconds() > PENDING_TTL_S for p in index.pending
            ):
                return 0
            orphans = await self.change(uid, stale)
            done: list[str] = []
            for o in orphans:
                try:
                    await self.drop_chunks(uid, o.fid, o.chunks)
                    done.append(o.fid)
                except Exception as exc:  # noqa: BLE001 - retried by the next sweep
                    log.warning("vault chunk sweep failed", extra={"error": type(exc).__name__})
            if done:
                await self.forget_orphans(uid, done)
            return len(done)
        except Exception as exc:  # noqa: BLE001 - housekeeping
            log.warning("vault sweep failed", extra={"error": type(exc).__name__})
            return 0

    async def forget_orphans(self, uid: str, fids: list[str]) -> None:
        def drop(index: VaultIndex) -> tuple[VaultIndex, None]:
            keep = tuple(o for o in index.orphans if o.fid not in fids)
            return index.model_copy(update={"orphans": keep}), None

        await self.change(uid, drop)

    async def delete_all(self, uid: str) -> None:
        """Remove the owner's index document (the wrapped keys go with it)."""
        await self._d.write([Delete(self._path(uid))])
        self._cache.pop(uid, None)


__all__ = ["MAX_BLOB_CHARS", "WRITE_GROUP", "VaultStore"]
