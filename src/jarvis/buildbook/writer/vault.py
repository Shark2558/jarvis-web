# src/jarvis/buildbook/writer/vault.py
"""R6.3 D11 (plan review M4, H3): the AI pages vault, one pages file a release, in its OWN sealed
index beside R6's (R6's `book/{uid}` index, `SealedRelease`, `seal.py` and the rest are never
touched, so a pre-R6.3 revision reading R6's index never sees a pages entry):

    {prefix}book_pages/{uid}                          {rev, kid, blob}  (`model.PagesIndex`)
    {prefix}book_pages/{uid}/book_chunks/{fid}_{nn}   R6's chunk envelope (`seal_chunks`)

The index is sealed under the keyring's existing `book_index` purpose with its own AAD
(`model.aad_pages_index`); a file's chunks use R6's envelope (`seal_index.BookCrypto.seal`).
`put` is attach OR replace: the chunks are written first as `pending`, the index last, in one
transaction that also moves the release's old chunk set to `orphans` (the newest pages file of a
release always wins) and reads R6's Privacy hold (`seal_state.held_of`): an attach in flight when
Privacy -> Delete lands is refused (`SealHeld`) and its chunks go. An attach that would pass the
storage limit (R6's sealed total plus every pages file) is refused (`BookOff`). Every read fails
closed (`VaultTampered`); nothing here logs a key, a blob, a path or page text.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
from collections.abc import Callable, Iterable
from typing import TypeVar

from pydantic import ValidationError

from jarvis.buildbook.ports import BookError, BookOff, VaultTampered
from jarvis.buildbook.seal_chunks import BookChunks
from jarvis.buildbook.seal_index import BookCrypto, Part
from jarvis.buildbook.seal_state import SealHeld, held_of, lease_path
from jarvis.buildbook.writer.model import (
    INDEX_PURPOSE,
    PAGES_FILE_CAP_BYTES,
    PAGES_INDEX,
    PagesEntry,
    PagesIndex,
    PagesPart,
    aad_pages_index,
)
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.storage.docs import Delete, Docs, DocTx

log = get_logger(__name__)
T = TypeVar("T")
DOWN = "The vault can't be reached right now."
TAMPERED = "The AI pages failed their check, so they stay closed."
HELD = "This release was deleted from your vault; its AI pages aren't sealed again."
FULL = "Sealing these AI pages would pass the build book's storage limit."
TOO_BIG = "This release's AI pages are over their size cap."
STALE_PENDING_S = 15 * 60  # R6's rule: a seal still pending after this died half-way


class PagesVault:
    def __init__(
        self, docs: Docs, ring: Keyring, *, prefix: str, clock: Callable[[], dt.datetime]
    ) -> None:
        self._d, self._ring, self._prefix, self._clock = docs, ring, prefix, clock
        self._c = BookCrypto(ring)
        self._col = f"{prefix}{PAGES_INDEX}"
        self._chunks = BookChunks(docs, self._col)

    def _path(self, uid: str) -> str:
        return f"{self._col}/{uid}"

    def _decode(self, uid: str, doc: dict[str, object] | None) -> tuple[int, PagesIndex]:
        if doc is None:
            return 0, PagesIndex()
        rev, blob = doc.get("rev"), doc.get("blob")
        if not isinstance(rev, int) or isinstance(rev, bool) or not isinstance(blob, str):
            raise VaultTampered(TAMPERED)
        try:
            raw = self._ring.cipher(INDEX_PURPOSE).decrypt(blob, aad=aad_pages_index(uid))
            return rev, PagesIndex.model_validate_json(raw)
        except (RuntimeError, ValidationError, ValueError) as exc:
            log.error("book pages index failed its check", extra={"error": type(exc).__name__})
            raise VaultTampered(TAMPERED) from None

    async def index(self, uid: str) -> PagesIndex:
        try:
            doc = await self._d.get(self._path(uid))
        except Exception as exc:  # noqa: BLE001 - any storage failure: nothing is read
            log.error("book pages index unreadable", extra={"error": type(exc).__name__})
            raise BookError(DOWN) from None
        return self._decode(uid, doc)[1]

    async def _change(
        self, uid: str, fn: Callable[[PagesIndex], tuple[PagesIndex, T]], *, held: str | None = None
    ) -> T:
        """Read-modify-write in one transaction (`fn` is pure); with `held`, stop with SealHeld
        when R6's Privacy hold names that release."""
        path, lease = self._path(uid), lease_path(self._prefix, uid)

        async def run(tx: DocTx) -> T:
            doc = await tx.get(path)
            if held is not None and held_of(await tx.get(lease)) == held:
                raise SealHeld(HELD)
            rev, ix = self._decode(uid, doc)
            new, result = fn(ix)
            if new != ix:
                key = self._ring.cipher(INDEX_PURPOSE)
                blob = key.encrypt(new.model_dump_json().encode(), aad=aad_pages_index(uid))
                tx.set(path, {"rev": rev + 1, "kid": self._ring.kid, "blob": blob})
            return result

        try:
            return await self._d.transaction(run)
        except BookError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.error("book pages index write failed", extra={"error": type(exc).__name__})
            raise BookError(DOWN) from None

    async def used_bytes(self, uid: str) -> int:
        return sum(f.size for f in (await self.index(uid)).files)

    async def put(
        self, uid: str, rid: str, data: bytes, *, counts: tuple[int, int, int], limit_bytes: int,
        others_bytes: int,
    ) -> PagesEntry:  # fmt: skip
        """Attach or replace `rid`'s pages file; `counts` = (written, changed, skipped)."""
        if len(data) > PAGES_FILE_CAP_BYTES:
            raise BookOff(TOO_BIG)
        ix = await self.index(uid)
        rest = sum(f.size for f in ix.files if f.release != rid)
        if others_bytes + rest + len(data) > limit_bytes:
            raise BookOff(FULL)
        now = self._clock()
        fid = f"bf_{secrets.token_hex(6)}"
        wrapped, blobs = self._c.seal(uid, rid, fid, data)
        entry = PagesEntry(
            release=rid, fid=fid, size=len(data), sha256=hashlib.sha256(data).hexdigest(),
            count=len(blobs), dek=wrapped, sealed_at=now.isoformat(), written=counts[0],
            changed=counts[1], skipped=counts[2],
        )  # fmt: skip
        part = PagesPart(fid=fid, count=len(blobs), since=now.isoformat())
        await self._change(uid, lambda i: (_add(i, pending=part), None), held=rid)
        try:
            await self._chunks.put(uid, fid, blobs, now.isoformat())
            orphans = await self._change(uid, lambda i: _commit(i, entry, part, now), held=rid)
        except Exception:
            await self._abandon(uid, part)
            raise
        await self._sweep(uid, orphans)
        return entry

    async def _abandon(self, uid: str, part: PagesPart) -> None:
        try:
            await self._chunks.drop(uid, Part(fid=part.fid, count=part.count, since=part.since))
            await self._change(uid, lambda i: (_without(i, {part.fid}), None))
        except Exception as exc:  # noqa: BLE001 - the next sweep retries
            log.warning("book pages cleanup deferred", extra={"error": type(exc).__name__})

    async def _sweep(self, uid: str, orphans: Iterable[PagesPart]) -> None:
        done: set[str] = set()
        for o in orphans:
            try:
                await self._chunks.drop(uid, Part(fid=o.fid, count=o.count, since=o.since))
                done.add(o.fid)
            except Exception as exc:  # noqa: BLE001 - kept as an orphan for the next run
                log.warning("book pages chunks left", extra={"error": type(exc).__name__})
        if done:
            await self._change(uid, lambda i: (_without(i, done), None))

    async def read(self, uid: str, rid: str) -> bytes:
        """`rid`'s pages file, checked (LookupError: none sealed; VaultTampered: a bad one)."""
        found = (await self.index(uid)).find(rid)
        if found is None:
            raise LookupError("No AI pages are sealed for that release.")
        try:
            dek = self._c.unwrap(uid, rid, found.fid, found.dek)
            plain = [
                self._c.open_chunk(
                    dek,
                    uid,
                    rid,
                    found.fid,
                    n,
                    found.count,
                    await self._chunks.get(uid, found.fid, n),
                )  # fmt: skip
                for n in range(found.count)
            ]
        except RuntimeError:
            log.error("a sealed AI pages file failed its check")
            raise VaultTampered(TAMPERED) from None
        data = b"".join(plain)
        if len(data) != found.size or hashlib.sha256(data).hexdigest() != found.sha256:
            log.error("a sealed AI pages file failed its checksum")
            raise VaultTampered(TAMPERED)
        return data

    async def drop(self, uid: str, rids: Iterable[str]) -> int:
        """Crypto-shred these releases' pages files (the entry first, the chunks after)."""
        gone = set(rids)
        now = self._clock()

        def shred(ix: PagesIndex) -> tuple[PagesIndex, tuple[int, tuple[PagesPart, ...]]]:
            out = [f for f in ix.files if f.release in gone]
            parts = tuple(PagesPart(fid=f.fid, count=f.count, since=now.isoformat()) for f in out)
            keep = tuple(f for f in ix.files if f.release not in gone)
            new = ix.model_copy(update={"files": keep, "orphans": (*ix.orphans, *parts)})
            return new, (len(out), new.orphans)

        if not gone:
            return 0
        count, orphans = await self._change(uid, shred)
        await self._sweep(uid, orphans)
        return count

    async def sweep_stale(self, uid: str, *, ttl_s: float = STALE_PENDING_S) -> int:
        """Pending sets older than the TTL (a process that died mid-seal) and orphans go."""
        now = self._clock()
        ix = await self.index(uid)
        old = [
            p
            for p in ix.pending
            if (now - dt.datetime.fromisoformat(p.since)).total_seconds() > ttl_s
        ]
        if old:
            fids = {p.fid for p in old}
            await self._change(uid, lambda i: (_orphaned(i, fids), None))
        orphans = (await self.index(uid)).orphans
        await self._sweep(uid, orphans)
        return len(orphans)

    async def delete_all(self, uid: str) -> int:
        """Every pages file (Privacy -> Delete): entries, then chunks, then the index document.
        An index that won't open goes too, its chunks found by listing."""
        try:
            ix = await self.index(uid)
        except VaultTampered:
            await self._chunks.drop_listed(uid)
            await self._d.write([Delete(self._path(uid))])
            return 1
        count = await self.drop(uid, [f.release for f in ix.files])
        await self.sweep_stale(uid, ttl_s=-1)
        left = await self.index(uid)
        if left == PagesIndex():
            await self._d.write([Delete(self._path(uid))])
        return count


def _add(ix: PagesIndex, *, pending: PagesPart) -> PagesIndex:
    return ix.model_copy(update={"pending": (*ix.pending, pending)})


def _without(ix: PagesIndex, fids: set[str]) -> PagesIndex:
    return ix.model_copy(
        update={
            "pending": tuple(p for p in ix.pending if p.fid not in fids),
            "orphans": tuple(o for o in ix.orphans if o.fid not in fids),
        }
    )


def _orphaned(ix: PagesIndex, fids: set[str]) -> PagesIndex:
    moved = tuple(p for p in ix.pending if p.fid in fids)
    keep = tuple(p for p in ix.pending if p.fid not in fids)
    return ix.model_copy(update={"pending": keep, "orphans": (*ix.orphans, *moved)})


def _commit(
    ix: PagesIndex, entry: PagesEntry, part: PagesPart, now: dt.datetime
) -> tuple[PagesIndex, tuple[PagesPart, ...]]:
    """Attach or replace (H3): the release's old chunk set becomes an orphan."""
    if part.fid not in {p.fid for p in ix.pending}:
        raise BookError("The seal was cleared before it finished; it will be tried again.")
    old = ix.find(entry.release)
    gone = () if old is None else (PagesPart(fid=old.fid, count=old.count, since=now.isoformat()),)
    files = (*(f for f in ix.files if f.release != entry.release), entry)
    pending = tuple(p for p in ix.pending if p.fid != part.fid)
    new = ix.model_copy(
        update={"files": files, "pending": pending, "orphans": (*ix.orphans, *gone)}
    )
    return new, new.orphans


__all__ = ["DOWN", "FULL", "HELD", "STALE_PENDING_S", "TAMPERED", "PagesVault"]
