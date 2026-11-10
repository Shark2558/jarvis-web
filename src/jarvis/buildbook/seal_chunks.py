# src/jarvis/buildbook/seal_chunks.py
"""The sealed build books' chunk documents (R6 D6; builder B; Layer 7), kept out of seal.py:

    {prefix}book/{uid}/book_chunks/{fid}_{nn}   {blob, n, of, at}

Written at most six a commit (~4.2 MB, under the 10 MiB request limit, as the R2 vault) and read
and deleted by path. One listing exists, for one case only: an index that won't open can still be
deleted (Privacy -> Delete), so its chunks are found by listing their collection, page by page (no
`where`, no order: no composite index). Errors carry fixed words; a log names an error's class
only, never a path, a blob or a key.
"""

from __future__ import annotations

from jarvis.buildbook.ports import BookError, VaultTampered
from jarvis.buildbook.seal_index import Part
from jarvis.logging import get_logger
from jarvis.storage.docs import Delete, Docs, Query, Set

log = get_logger(__name__)

WRITE_GROUP = 6  # chunks a commit (~4.2 MB, under the 10 MiB request limit), as the R2 vault
DELETE_GROUP = 200
LIST_PAGE = 200  # chunk documents a listing page (unreadable index only)
LIST_PAGES_MAX = 50  # 10,000 documents: far past 3 releases of 15 MB plus any orphans
DOWN = "The vault can't be reached right now."
MISSING = "A part of a sealed build book is missing."


class BookChunks:
    def __init__(self, docs: Docs, col: str) -> None:
        self._d = docs
        self._col = col

    def collection(self, uid: str) -> str:
        return f"{self._col}/{uid}/book_chunks"

    def path(self, uid: str, fid: str, n: int) -> str:
        return f"{self.collection(uid)}/{fid}_{n:02d}"

    async def put(self, uid: str, fid: str, blobs: list[str], at: str) -> None:
        total = len(blobs)
        for start in range(0, total, WRITE_GROUP):
            ops = [
                Set(self.path(uid, fid, n), {"blob": blobs[n], "n": n, "of": total, "at": at})
                for n in range(start, min(total, start + WRITE_GROUP))
            ]
            try:
                await self._d.write(ops)
            except Exception as exc:  # noqa: BLE001
                log.error("book chunk write failed", extra={"error": type(exc).__name__})
                raise BookError(DOWN) from None

    async def drop(self, uid: str, part: Part) -> None:
        """Delete one chunk set by path (safe to repeat); raises when storage refuses."""
        paths = [self.path(uid, part.fid, n) for n in range(part.count)]
        for start in range(0, len(paths), DELETE_GROUP):
            await self._d.write([Delete(p) for p in paths[start : start + DELETE_GROUP]])

    async def get(self, uid: str, fid: str, n: int) -> str:
        try:
            doc = await self._d.get(self.path(uid, fid, n))
        except Exception as exc:  # noqa: BLE001
            log.error("book chunk unreadable", extra={"error": type(exc).__name__})
            raise BookError(DOWN) from None
        blob = (doc or {}).get("blob")
        if not isinstance(blob, str):
            raise VaultTampered(MISSING)
        return blob

    async def drop_listed(self, uid: str) -> set[str]:
        """Delete every chunk document of `uid` found by listing (an index that won't open);
        returns the chunk sets (file ids) that went. BookError when storage refuses."""
        fids: set[str] = set()
        col = self.collection(uid)
        try:
            for _ in range(LIST_PAGES_MAX):
                rows = await self._d.query(Query(col, limit=LIST_PAGE))
                if not rows:
                    break
                await self._d.write([Delete(f"{col}/{doc_id}") for doc_id, _ in rows])
                fids.update(doc_id.rsplit("_", 1)[0] for doc_id, _ in rows)
        except Exception as exc:  # noqa: BLE001 - the next delete lists again
            log.error("book chunks not swept", extra={"error": type(exc).__name__})
            raise BookError(DOWN) from None
        return fids


__all__ = [
    "DELETE_GROUP",
    "LIST_PAGE",
    "LIST_PAGES_MAX",
    "WRITE_GROUP",
    "BookChunks",
]
