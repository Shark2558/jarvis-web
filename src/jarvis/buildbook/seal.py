# src/jarvis/buildbook/seal.py
"""Sealed build books in the vault family (R6 D6; builder B; Layer 7, cross-cutting security).

    {prefix}book/{uid}                          {rev, kid, blob}
    {prefix}book/{uid}/book_chunks/{fid}_{nn}   {blob, n, of, at}

`blob` is the `seal_index.BookIndex` sealed under keyring purpose `book_index`; the chunks use the
R2 vault's envelope with D6's AADs (`seal_index.BookCrypto`). A seal records its chunk set as
pending, writes the chunks at most six a commit, then commits the index (the release exists only
from then on). Prune drops the index entry first (crypto-shred: the wrapped keys go with it) and
the chunks by path after; a delete that fails stays an orphan for the next run, and a pending set
older than 15 minutes (a process that died mid-seal) is swept the same way. Every read fails
closed: an index that won't open, a chunk that's missing or won't open, or bytes that don't match
their SHA-256 raise `VaultTampered`, and the index is then never overwritten. Nothing here logs a
key, a blob, book text or a path; errors carry fixed words.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
from collections.abc import Callable, Mapping
from typing import TypeVar

from pydantic import ValidationError

from jarvis.buildbook.model import (
    BOOK_JSON_CAP_BYTES,
    KEEP,
    MIB,
    SNAPSHOT_CAP_BYTES,
    FileKind,
    Release,
    SealedFile,
    SealedRelease,
)
from jarvis.buildbook.ports import BookError, BookOff, BookUnavailable, VaultTampered
from jarvis.buildbook.seal_index import BookCrypto, BookIndex, Part, age, parts_of
from jarvis.integrations.vault import VaultError
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.storage.docs import Delete, Docs, DocTx, Set

log = get_logger(__name__)
T = TypeVar("T")

WRITE_GROUP = 6  # chunks a commit (~4.2 MB, under the 10 MiB request limit), as the R2 vault
DELETE_GROUP = 200
PENDING_TTL_S = 15 * 60  # a seal still pending after this died half-way: its chunks are swept
MAX_INDEX_CHARS = 200_000
KINDS: tuple[FileKind, ...] = ("book", "source")
CAPS: Mapping[FileKind, int] = {"book": BOOK_JSON_CAP_BYTES, "source": SNAPSHOT_CAP_BYTES}
DOWN = "The vault can't be reached right now."
TAMPERED = "The sealed build books failed their check, so they stay closed."


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _checked(release: Release, files: Mapping[FileKind, bytes]) -> dict[FileKind, bytes]:
    if not release.ok:
        raise BookUnavailable("This release has no build book.")
    if set(files) != set(KINDS):
        raise ValueError("a sealed release is its book and its source snapshot")
    want = {"book": release.book_sha256, "source": release.source_sha256}
    for kind in KINDS:
        if len(files[kind]) > CAPS[kind]:
            raise BookUnavailable("A file of this release is over its size cap.")
        if hashlib.sha256(files[kind]).hexdigest() != want[kind]:
            raise BookUnavailable("The files don't match their release.")
    return {kind: files[kind] for kind in KINDS}


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
        self._limit = limit_mb * MIB
        self._limit_mb = limit_mb
        self._clock = clock

    @property
    def limit_mb(self) -> int:
        return self._limit_mb

    def _path(self, uid: str) -> str:
        return f"{self._col}/{uid}"

    def _chunk_path(self, uid: str, fid: str, n: int) -> str:
        return f"{self._col}/{uid}/book_chunks/{fid}_{n:02d}"

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

    async def _change(self, uid: str, fn: Callable[[BookIndex], tuple[BookIndex, T]]) -> T:
        """Read-modify-write in one transaction. `fn` is pure (it may run again) and may raise a
        BookError to stop; an index that won't open is never replaced; no change, no write."""
        path = self._path(uid)

        async def run(tx: DocTx) -> T:
            rev, index = self._decode(uid, await tx.get(path))
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

    # ---- chunks, by path only ----------------------------------------------------------------

    async def _put(self, uid: str, fid: str, blobs: list[str], at: str) -> None:
        total = len(blobs)
        for start in range(0, total, WRITE_GROUP):
            ops = [
                Set(
                    self._chunk_path(uid, fid, n), {"blob": blobs[n], "n": n, "of": total, "at": at}
                )
                for n in range(start, min(total, start + WRITE_GROUP))
            ]
            try:
                await self._d.write(ops)
            except Exception as exc:  # noqa: BLE001
                log.error("book chunk write failed", extra={"error": type(exc).__name__})
                raise BookError(DOWN) from None

    async def _drop(self, uid: str, part: Part) -> None:
        """Delete one chunk set by path (safe to repeat); raises when storage refuses."""
        paths = [self._chunk_path(uid, part.fid, n) for n in range(part.count)]
        for start in range(0, len(paths), DELETE_GROUP):
            await self._d.write([Delete(p) for p in paths[start : start + DELETE_GROUP]])

    async def _chunk(self, uid: str, fid: str, n: int) -> str:
        try:
            doc = await self._d.get(self._chunk_path(uid, fid, n))
        except Exception as exc:  # noqa: BLE001
            log.error("book chunk unreadable", extra={"error": type(exc).__name__})
            raise BookError(DOWN) from None
        blob = (doc or {}).get("blob")
        if not isinstance(blob, str):
            raise VaultTampered("A part of a sealed build book is missing.")
        return blob

    async def _sweep(self, uid: str, orphans: tuple[Part, ...]) -> None:
        """Delete orphan chunk sets; the ones whose delete failed stay for the next run."""
        done: set[str] = set()
        for part in orphans:
            try:
                await self._drop(uid, part)
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
        data = _checked(release, files)
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
            uid, lambda ix: (ix.model_copy(update={"pending": (*ix.pending, *parts)}), None)
        )
        try:
            for f, blobs in sealed:
                await self._put(uid, f.fid, blobs, now.isoformat())
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
        fid = f"bf_{secrets.token_hex(6)}"
        try:
            wrapped, blobs = self._c.seal(uid, rid, fid, data)
        except VaultError:
            raise BookOff("The build book could not be sealed.") from None
        digest = hashlib.sha256(data).hexdigest()
        meta = SealedFile(
            kind=kind, fid=fid, size=len(data), sha256=digest, count=len(blobs), dek=wrapped
        )
        return meta, blobs

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

        return await self._change(uid, fn)

    async def _abandon(self, uid: str, parts: tuple[Part, ...]) -> None:
        """A seal failed half-way: its chunks go by path; if even that fails, the TTL sweep will."""
        ours = {p.fid for p in parts}
        try:
            for part in parts:
                await self._drop(uid, part)

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
            blob = await self._chunk(uid, f.fid, n)
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
        index document goes once nothing is left to retry. Returns how many releases went."""
        now = self._clock()
        if await self._load(uid) == BookIndex():
            return 0

        def clear(ix: BookIndex) -> tuple[BookIndex, tuple[int, tuple[Part, ...]]]:
            parts = tuple(p for r in ix.releases for p in parts_of(r, now))
            orphans = (*ix.orphans, *parts, *ix.pending)
            return BookIndex(orphans=orphans), (len(ix.releases), orphans)

        count, orphans = await self._change(uid, clear)
        await self._sweep(uid, orphans)
        if await self._load(uid) == BookIndex():
            try:
                await self._d.write([Delete(self._path(uid))])
            except Exception as exc:  # noqa: BLE001 - an empty index is harmless
                log.warning("empty book index not removed", extra={"error": type(exc).__name__})
        return count


__all__ = [
    "CAPS",
    "DELETE_GROUP",
    "KINDS",
    "PENDING_TTL_S",
    "WRITE_GROUP",
    "DocsBookVault",
]
