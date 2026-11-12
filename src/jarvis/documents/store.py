# src/jarvis/documents/store.py
"""Attachments on the Docs port (slice 10 E; Firestore in prod, MemoryDocs in tests).

Layout:  {prefix}attachments/{id}                   header (`Attachment`): owner, session, turn,
                                                    name, kind, counts, preview (≤ 2,000 chars)
         {prefix}attachments/{id}/chunks/{000001}   text (≈ 4,000 chars), start, page, page_end
         {prefix}attachments/{id}/pictures/{01}     R11.1 D10: name, media_type, data (the
                                                    cleaned bytes, ≤ 900 KB; at most 4)

Every document stays under Firestore's 1 MiB limit (a picture is capped at 900 KB for that). An
upload is one commit (≤ 480 chunks + ≤ 4 pictures + the header, header LAST and create-only).
Binding uploads to the conversation they were sent in is one transaction over all of them:
owner-checked, only while still waiting, all or nothing; `unbind` undoes it when the turn could
not be stored.
Chunk texts of the few most recent documents are kept in-process (doc_search reads them all);
a doc_read part reads only its own chunks (integration review M2). The cache holds as many
documents as one owner message may call document tools (`tools.budget.MAX_DOC_CALLS`), so one
message's calls never evict each other (review L5).
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError

from jarvis.documents.chunking import Chunk
from jarvis.documents.models import DOC_ID, Attachment, StoredPicture
from jarvis.logging import get_logger
from jarvis.storage.docs import Create, Delete, Doc, Docs, DocTx, Op, Query, Set
from jarvis.tools.budget import MAX_DOC_CALLS

log = get_logger(__name__)

CACHE_DOCS = MAX_DOC_CALLS  # ≤ 6 × 300,000 characters in memory at most


class NotAvailable(LookupError):
    """An attachment that is missing, someone else's, or already sent."""


def _parse(aid: str, raw: Doc | None) -> Attachment | None:
    if raw is None:
        return None
    try:
        return Attachment.model_validate(raw)
    except ValidationError:
        log.error("unreadable attachment header", extra={"attachment": aid})
        return None


def _chunk_doc(c: Chunk) -> Doc:
    return {"text": c.text, "start": c.start, "page": c.page, "page_end": c.page_end}


def _chunk_of(d: Doc) -> Chunk:
    return Chunk(str(d["text"]), int(d["start"]), d.get("page"), d.get("page_end"))


class AttachmentStore:
    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self._d = docs
        self._col = f"{prefix}attachments"
        self._cache: OrderedDict[str, list[Chunk]] = OrderedDict()

    def _head(self, aid: str) -> str:
        return f"{self._col}/{aid}"

    def _chunks_col(self, aid: str) -> str:
        return f"{self._col}/{aid}/chunks"

    def _pictures_col(self, aid: str) -> str:
        return f"{self._col}/{aid}/pictures"

    async def create(
        self, att: Attachment, chunks: Sequence[Chunk], pictures: Sequence[StoredPicture] = ()
    ) -> None:
        ops: list[Op] = [
            Set(f"{self._chunks_col(att.id)}/{i + 1:06d}", _chunk_doc(c))
            for i, c in enumerate(chunks)
        ]
        ops += [
            Set(f"{self._pictures_col(att.id)}/{i + 1:02d}", p.model_dump())
            for i, p in enumerate(pictures)
        ]
        ops.append(Create(self._head(att.id), att.model_dump()))  # last: makes the rest visible
        await self._d.write(ops)

    async def pictures(self, att: Attachment) -> list[StoredPicture]:
        """The cleaned pictures kept with `att`, in the order they were found (R11.1 D10)."""
        if att.pictures <= 0:
            return []
        rows = await self._d.query(Query(self._pictures_col(att.id), limit=att.pictures))
        out: list[StoredPicture] = []
        for _, raw in sorted(rows, key=lambda row: row[0]):
            try:
                out.append(StoredPicture.model_validate(raw))
            except ValidationError:
                log.error("unreadable stored picture", extra={"attachment": att.id})
        return out

    async def get(self, aid: str) -> Attachment | None:
        if not DOC_ID.fullmatch(aid):
            return None
        return _parse(aid, await self._d.get(self._head(aid)))

    async def part(self, att: Attachment, start: int, stop: int) -> list[Chunk]:
        """Chunks [start, stop) only (a doc_read part): sliced from the cache when the document
        is there, else read by path — never the whole document, never cached (so reading parts
        can't push a searched document out of the cache)."""
        stop = min(stop, att.chunk_count)
        cached = self._cache.get(att.id)
        if cached is not None:
            return list(cached[start:stop])
        if start >= stop:
            return []
        raws = await asyncio.gather(
            *(self._d.get(f"{self._chunks_col(att.id)}/{i + 1:06d}") for i in range(start, stop))
        )
        return [_chunk_of(d) for d in raws if d is not None]

    async def chunks(self, att: Attachment) -> list[Chunk]:
        """Every chunk (doc_search ranks them all), cached for the few most recent documents."""
        cached = self._cache.get(att.id)
        if cached is not None:
            self._cache.move_to_end(att.id)
            return list(cached)
        rows = await self._d.query(Query(self._chunks_col(att.id), limit=att.chunk_count))
        out = [_chunk_of(d) for _, d in rows]
        if out:
            self._cache[att.id] = out
            while len(self._cache) > CACHE_DOCS:
                self._cache.popitem(last=False)
        return list(out)

    async def bind(
        self, ids: Sequence[str], *, owner: str, session_id: str, turn_id: str
    ) -> list[Attachment]:
        """Tie waiting uploads to the conversation and turn they were sent with (atomic)."""

        async def run(tx: DocTx) -> list[Attachment]:
            heads = [(aid, await tx.get(self._head(aid))) for aid in ids]
            bound: list[Attachment] = []
            for aid, raw in heads:
                a = _parse(aid, raw)
                if a is None or a.owner != owner or not a.waiting:
                    raise NotAvailable(aid)
                bound.append(a.model_copy(update={"session": session_id, "turn": turn_id}))
            for a in bound:
                tx.set(self._head(a.id), a.model_dump())
            return bound

        if not all(DOC_ID.fullmatch(aid) for aid in ids):
            raise NotAvailable("malformed id")
        return await self._d.transaction(run)

    async def unbind(self, ids: Sequence[str], *, owner: str, turn_id: str) -> None:
        """Undo `bind` for a turn that could not be stored: back to waiting (only files that
        are the owner's and still bound to exactly that turn)."""

        async def run(tx: DocTx) -> None:
            heads = [(aid, await tx.get(self._head(aid))) for aid in ids if DOC_ID.fullmatch(aid)]
            for aid, raw in heads:
                a = _parse(aid, raw)
                if a is not None and a.owner == owner and a.turn == turn_id:
                    tx.set(
                        self._head(aid),
                        a.model_copy(update={"session": "", "turn": ""}).model_dump(),
                    )

        await self._d.transaction(run)

    async def delete(self, aid: str) -> None:
        """Chunks and pictures first, header LAST: an interrupted delete is found and finished
        next time."""
        self._cache.pop(aid, None)
        rows = await self._d.query(Query(self._chunks_col(aid)))
        ops: list[Op] = [Delete(f"{self._chunks_col(aid)}/{cid}") for cid, _ in rows]
        shots = await self._d.query(Query(self._pictures_col(aid)))
        ops += [Delete(f"{self._pictures_col(aid)}/{pid}") for pid, _ in shots]
        ops.append(Delete(self._head(aid)))
        await self._d.write(ops)

    async def _where(self, field: str, value: Any) -> list[Attachment]:
        rows = await self._d.query(Query(self._col, where=(field, value)))
        return [a for aid, d in rows if (a := _parse(aid, d)) is not None]

    async def in_session(self, session_id: str) -> list[Attachment]:
        return await self._where("session", session_id)

    async def waiting(self) -> list[Attachment]:
        return await self._where("session", "")


__all__ = ["AttachmentStore", "NotAvailable"]
