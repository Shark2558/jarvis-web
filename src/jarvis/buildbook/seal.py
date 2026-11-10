# src/jarvis/buildbook/seal.py
"""Sealed build books in the vault family (R6 D6; builder B; Layer 7, cross-cutting security).

    {prefix}book/{uid}                          {rev, kid, blob}
    {prefix}book/{uid}/book_chunks/{fid}_{nn}   {blob, n, of, at}   (seal_chunks.BookChunks)

`blob` is the `seal_index.BookIndex` sealed under keyring purpose `book_index`; the chunks use the
R2 vault's envelope with D6's AADs (`seal_index.BookCrypto`). A seal records its chunk set as
pending, writes the chunks at most six a commit, then commits the index; both index steps also
read the sealer's document and stop (`SealHeld`) when Privacy -> Delete held that release, so a
seal in flight when the owner deletes everything can't bring it back. Prune drops the index entry
first (crypto-shred) and the chunks by path after; a failed delete stays an orphan for the next
run, as does a pending set older than 15 minutes (a process that died mid-seal). Every read fails
closed (`VaultTampered`): an index that won't open is never overwritten, only deleted (its chunks
then found by listing). Nothing here logs a key, a blob, book text or a path.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Callable, Mapping
from typing import TypeVar

from pydantic import ValidationError

from jarvis.buildbook.model import KEEP, MIB, FileKind, Release, SealedFile, SealedRelease
from jarvis.buildbook.ports import BookError, BookOff, VaultTampered
from jarvis.buildbook.seal_chunks import DELETE_GROUP, WRITE_GROUP, BookChunks
from jarvis.buildbook.seal_index import (
    CAPS,
    KINDS,
    BookCrypto,
    BookIndex,
    Part,
    age,
    checked_files,
    parts_of,
)
from jarvis.buildbook.seal_state import SealHeld, held_of, lease_path
from jarvis.integrations.vault import VaultError
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.storage.docs import Docs, DocTx

log = get_logger(__name__)
T = TypeVar("T")

PENDING_TTL_S = 15 * 60  # a seal still pending after this died half-way: its chunks are swept
MAX_INDEX_CHARS = 200_000
DOWN = "The vault can't be reached right now."
TAMPERED = "The sealed build books failed their check, so they stay closed."
HELD = "This release was deleted from your vault; it isn't sealed again."


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class DocsBookVault:
    """`ports.BookVault` on the Docs port (Firestore in production, MemoryDocs in tests)."""

    def __init__(
        self,
        docs: Docs,
        ring: Keyring,
        *,
        prefix: str = "jarvis_",
        limit_mb: int = 60,
        clock: Callable[[], dt.datetime] = _now,
    ) -> None:
        self._d = docs
        self._c = BookCrypto(ring)
        self._col = f"{prefix}book"
        self._prefix = prefix
        self._chunks = BookChunks(docs, self._col)
        self._limit = limit_mb * MIB
        self._limit_mb = limit_mb
        self._clock = clock

    @property
    def limit_mb(self) -> int:
        return self._limit_mb

    def _path(self, uid: str) -> str:
        return f"{self._col}/{uid}"

    # ---- the index -----------------------------------------------------------------------------

    def _decode(self, uid: str, doc: dict[str, object] | None) -> tuple[int, BookIndex]:
        if doc is None:
            return 0, BookIndex()
        rev, blob = doc.get("rev"), doc.get("blob")
        if not isinstance(rev, int) or isinstance(rev, bool) or not isinstance(blob, str):
            raise VaultTampered(TAMPERED)
        try:
            return rev, BookIndex.model_validate_json(self._c.open_index(uid, blob))
        except (VaultError, ValidationError, ValueError) as exc:
            log.error("book index failed its check", extra={"error": type(exc).__name__})
            raise VaultTampered(TAMPERED) from None

    async def _load(self, uid: str) -> BookIndex:
        try:
            doc = await self._d.get(self._path(uid))
        except Exception as exc:  # noqa: BLE001 - any storage failure: nothing is read
            log.error("book index unreadable", extra={"error": type(exc).__name__})
            raise BookError(DOWN) from None
        return self._decode(uid, doc)[1]

    async def _change(
        self, uid: str, fn: Callable[[BookIndex], tuple[BookIndex, T]], *, held: str | None = None
    ) -> T:
        """Read-modify-write in one transaction. `fn` is pure (it may run again) and may raise a
        BookError to stop; an index that won't open is never replaced; no change, no write. With
        `held` (a release id) it stops with SealHeld when Privacy held that release."""
        path, lease = self._path(uid), lease_path(self._prefix, uid)

        async def run(tx: DocTx) -> T:
            doc = await tx.get(path)
            if held is not None and held_of(await tx.get(lease)) == held:
                raise SealHeld(HELD)
            rev, index = self._decode(uid, doc)
            new, result = fn(index)
            if new == index:
                return result
            blob = self._c.seal_index(uid, new.model_dump_json().encode())
            if len(blob) > MAX_INDEX_CHARS:
                raise BookOff("The book index is full.")
            tx.set(path, {"rev": rev + 1, "kid": self._c.kid, "blob": blob})
            return result

        try:
            return await self._d.transaction(run)
        except BookError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.error("book index write failed", extra={"error": type(exc).__name__})
            raise BookError(DOWN) from None

    async def _drop_index(self, uid: str, *, unreadable: bool) -> None:
        """Delete the index document in a transaction only while it is still empty (or, with
        `unreadable`, still won't open), so a seal that lands meanwhile keeps its entry."""
        path = self._path(uid)

        async def run(tx: DocTx) -> None:
            doc = await tx.get(path)
            if doc is None:
                return
            try:
                empty = self._decode(uid, doc)[1] == BookIndex()
            except VaultTampered:
                drop = unreadable
            else:
                drop = empty and not unreadable
            if drop:
                tx.delete(path)

        try:
            await self._d.transaction(run)
        except Exception as exc:  # noqa: BLE001 - an empty index is harmless; an unreadable one
            log.warning("book index not removed", extra={"error": type(exc).__name__})
            if unreadable:  # must go: the delete is answered as failed and can be asked again
                raise BookError(DOWN) from None

    async def _sweep(self, uid: str, orphans: tuple[Part, ...]) -> None:
        """Delete orphan chunk sets; the ones whose delete failed stay for the next run."""
        done: set[str] = set()
        for part in orphans:
            try:
                await self._chunks.drop(uid, part)
                done.add(part.fid)
            except Exception as exc:  # noqa: BLE001 - kept as an orphan; the next run retries
                log.warning(
                    "book chunks left for the next run", extra={"error": type(exc).__name__}
                )
        if done:

            def forget(ix: BookIndex) -> tuple[BookIndex, None]:
                keep = tuple(o for o in ix.orphans if o.fid not in done)
                return ix.model_copy(update={"orphans": keep}), None

            await self._change(uid, forget)

    # ---- the port ----------------------------------------------------------------------------

    async def releases(self, uid: str) -> tuple[SealedRelease, ...]:
        return (await self._load(uid)).newest_first()

    async def used_bytes(self, uid: str) -> int:
        return (await self._load(uid)).size()

    async def seal(
        self, uid: str, release: Release, files: Mapping[FileKind, bytes], *, now: dt.datetime
    ) -> SealedRelease:
        data = checked_files(release, files)
        index = await self._load(uid)
        found = index.find(release.id)
        if found is not None:
            return found
        if index.size() + sum(len(b) for b in data.values()) > self._limit:
            raise BookOff("Sealing this release would pass the build book's storage limit.")
        sealed = [self._seal_file(uid, release.id, kind, data[kind]) for kind in KINDS]
        entry = SealedRelease(
            **release.ref().model_dump(),
            sealed_at=now.isoformat(),
            files=tuple(f for f, _ in sealed),
        )
        parts = parts_of(entry, now)
        await self._change(
            uid,
            lambda ix: (ix.model_copy(update={"pending": (*ix.pending, *parts)}), None),
            held=release.id,
        )
        try:
            for f, blobs in sealed:
                await self._chunks.put(uid, f.fid, blobs, now.isoformat())
            result, raced = await self._commit(uid, entry, parts)
        except Exception:
            await self._abandon(uid, parts)
            raise
        if raced:  # another sealer committed this release first: our chunks go
            await self._sweep(uid, parts)
        return result

    def _seal_file(
        self, uid: str, rid: str, kind: FileKind, data: bytes
    ) -> tuple[SealedFile, list[str]]:
        try:
            return self._c.seal_file(uid, rid, kind, data)
        except VaultError:
            raise BookOff("The build book could not be sealed.") from None

    async def _commit(
        self, uid: str, entry: SealedRelease, parts: tuple[Part, ...]
    ) -> tuple[SealedRelease, bool]:
        """The index step: (the sealed release, whether another sealer had committed it)."""
        ours = {p.fid for p in parts}

        def fn(ix: BookIndex) -> tuple[BookIndex, tuple[SealedRelease, bool]]:
            if not ours <= {p.fid for p in ix.pending}:
                raise BookError("The seal was cleared before it finished; it will be tried again.")
            rest = tuple(p for p in ix.pending if p.fid not in ours)
            existing = ix.find(entry.id)
            if existing is not None:
                orphans = (*ix.orphans, *parts)
                return ix.model_copy(update={"pending": rest, "orphans": orphans}), (existing, True)
            new = ix.model_copy(update={"releases": (*ix.releases, entry), "pending": rest})
            return new, (entry, False)

        return await self._change(uid, fn, held=entry.id)

    async def _abandon(self, uid: str, parts: tuple[Part, ...]) -> None:
        """A seal failed half-way: its chunks go by path; if even that fails, the TTL sweep will."""
        ours = {p.fid for p in parts}
        try:
            for part in parts:
                await self._chunks.drop(uid, part)

            def clear(ix: BookIndex) -> tuple[BookIndex, None]:
                keep = tuple(p for p in ix.pending if p.fid not in ours)
                return ix.model_copy(update={"pending": keep}), None

            await self._change(uid, clear)
        except Exception as exc:  # noqa: BLE001
            log.warning("book seal cleanup deferred", extra={"error": type(exc).__name__})

    async def prune(self, uid: str, *, keep: int = KEEP) -> tuple[str, ...]:
        if isinstance(keep, bool) or not isinstance(keep, int) or keep < 1:
            raise ValueError("keep at least one release (delete_all removes them all)")
        now = self._clock()
        index = await self._load(uid)
        stale = [p for p in index.pending if age(p, now) > PENDING_TTL_S]
        if len(index.releases) <= keep and not index.orphans and not stale:
            return ()

        def shred(ix: BookIndex) -> tuple[BookIndex, tuple[tuple[str, ...], tuple[Part, ...]]]:
            ordered = ix.newest_first()
            kept = {r.id for r in ordered[:keep]}
            gone = ordered[keep:]
            old = tuple(p for p in ix.pending if age(p, now) > PENDING_TTL_S)
            orphans = (*ix.orphans, *(p for r in gone for p in parts_of(r, now)), *old)
            new = ix.model_copy(
                update={
                    "releases": tuple(r for r in ix.releases if r.id in kept),
                    "pending": tuple(p for p in ix.pending if p not in old),
                    "orphans": orphans,
                }
            )
            return new, (tuple(r.id for r in gone), orphans)

        removed, orphans = await self._change(uid, shred)
        await self._sweep(uid, orphans)
        return removed

    async def read(self, uid: str, rid: str, kind: FileKind) -> bytes:
        found = (await self._load(uid)).find(rid)
        if found is None:
            raise LookupError("That release isn't sealed in your vault.")
        f = found.file(kind)
        try:
            dek = self._c.unwrap(uid, rid, f.fid, f.dek)
        except VaultError:
            log.error("a sealed build book's key failed its check")
            raise VaultTampered(TAMPERED) from None
        plain: list[bytes] = []
        for n in range(f.count):
            blob = await self._chunks.get(uid, f.fid, n)
            try:
                plain.append(self._c.open_chunk(dek, uid, rid, f.fid, n, f.count, blob))
            except VaultError:
                log.error("a sealed build book chunk failed its check")
                raise VaultTampered(TAMPERED) from None
        data = b"".join(plain)
        if len(data) != f.size or hashlib.sha256(data).hexdigest() != f.sha256:
            log.error("a sealed build book failed its checksum")
            raise VaultTampered(TAMPERED)
        return data

    async def delete_all(self, uid: str) -> int:
        """Every sealed release (Privacy -> Delete): the index entries first, then the chunks; the
        index document goes once nothing is left to retry. Returns how many releases went. An
        index that won't open is deleted too (`_delete_unreadable`)."""
        now = self._clock()
        try:
            index = await self._load(uid)
        except VaultTampered:
            return await self._delete_unreadable(uid)
        count = 0
        if index != BookIndex():

            def clear(ix: BookIndex) -> tuple[BookIndex, tuple[int, tuple[Part, ...]]]:
                parts = tuple(p for r in ix.releases for p in parts_of(r, now))
                orphans = (*ix.orphans, *parts, *ix.pending)
                return BookIndex(orphans=orphans), (len(ix.releases), orphans)

            count, orphans = await self._change(uid, clear)
            await self._sweep(uid, orphans)
        await self._drop_index(uid, unreadable=False)
        return count

    async def _delete_unreadable(self, uid: str) -> int:
        """An index that won't open (tampered, or a changed token key) is never read, but it can
        go: every chunk found by listing first (no seal can start against it meanwhile: each one
        fails closed on it), then the index document, while it still won't open. Returns the
        releases that went as the chunk sets tell (two a release), at least 1."""
        fids = await self._chunks.drop_listed(uid)
        await self._drop_index(uid, unreadable=True)
        log.warning("an unreadable build book index was deleted")
        return max(1, (len(fids) + 1) // 2)


__all__ = ["CAPS", "DELETE_GROUP", "KINDS", "PENDING_TTL_S", "WRITE_GROUP", "DocsBookVault"]
