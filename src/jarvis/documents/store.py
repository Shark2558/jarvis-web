# src/jarvis/documents/store.py
"""Attachments on the Docs port (slice 10 E; Firestore in prod, MemoryDocs in tests).

Layout:  {prefix}attachments/{id}                   header (`Attachment`): owner, session, turn,
                                                    name, kind, counts, preview (≤ 2,000 chars)
         {prefix}attachments/{id}/chunks/{000001}   text (≈ 4,000 chars), start, page, page_end

Every document stays far under Firestore's 1 MiB limit. An upload is one commit (≤ 480 chunks +
the header, header LAST and create-only). Binding uploads to the conversation they were sent in
is one transaction over all of them: owner-checked, only while still waiting, all or nothing.
Chunk texts of the few most recent documents are kept in-process (doc_search reads them all).
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError

from jarvis.documents.chunking import Chunk
from jarvis.documents.models import DOC_ID, Attachment
from jarvis.logging import get_logger
from jarvis.storage.docs import Create, Delete, Doc, Docs, DocTx, Op, Query, Set

log = get_logger(__name__)

CACHE_DOCS = 4


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

    async def create(self, att: Attachment, chunks: Sequence[Chunk]) -> None:
        ops: list[Op] = [
            Set(f"{self._chunks_col(att.id)}/{i + 1:06d}", _chunk_doc(c))
            for i, c in enumerate(chunks)
        ]
        ops.append(Create(self._head(att.id), att.model_dump()))  # last: makes the rest visible
        await self._d.write(ops)

    async def get(self, aid: str) -> Attachment | None:
        if not DOC_ID.fullmatch(aid):
            return None
        return _parse(aid, await self._d.get(self._head(aid)))

    async def chunks(self, att: Attachment) -> list[Chunk]:
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

    async def delete(self, aid: str) -> None:
        """Chunks first, header LAST: an interrupted delete is found and finished next time."""
        self._cache.pop(aid, None)
        rows = await self._d.query(Query(self._chunks_col(aid)))
        ops: list[Op] = [Delete(f"{self._chunks_col(aid)}/{cid}") for cid, _ in rows]
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
