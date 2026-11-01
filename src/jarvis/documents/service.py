# src/jarvis/documents/service.py
"""Attached documents, end to end (slice 10 E; Layer 2 input → 7 data → 5 skill).

upload   name → type (extension + magic bytes) → text in a worker thread with a time budget
         (≤ 2 extractions running; a hung one keeps its slot until it ends: "busy", never a
         pile of CPU-burning threads) → chunks → one commit. The file itself is dropped.
         Waiting uploads: ≤ 10 per owner; older than a day → swept at the next upload.
attach   on send (inside the Brain's per-conversation lock): refused for a training brain;
         ≤ 3 per message; each must be the owner's and still waiting; bound atomically to
         the conversation and the turn; the turn gets a second text block (`render_note`).
read / search (the doc_read / doc_search tools): only the owner's files, only in the
         conversation they were sent in. Text is fenced as external content.
forget_session  the owner deleted the conversation: its files go too (before the turns).
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from jarvis.core.guardrails import InputRejected
from jarvis.core.models import ChatRequest, Turn
from jarvis.documents.chunking import excerpt, pages_label, rank, split
from jarvis.documents.extract import Extracted, Limits, extract, kind_for, sniff
from jarvis.documents.models import (
    CHUNKS_PER_PART,
    MAX_FILE_BYTES,
    MAX_FILES_PER_MESSAGE,
    MAX_WAITING,
    PREVIEW_CHARS,
    Attachment,
    AttachmentRef,
    DocumentRejected,
    new_doc_id,
)
from jarvis.documents.note import clean_name, render_note
from jarvis.documents.store import AttachmentStore, NotAvailable
from jarvis.llm.base import TextBlock
from jarvis.llm.brains import BrainSpec
from jarvis.logging import get_logger
from jarvis.tools.external import wrap_external

log = get_logger(__name__)

MAX_RUNNING = 2
GRACE_S = 2.0  # beyond the extractor's own between-pages budget
WAITING_TTL = timedelta(hours=24)
TOP_HITS = 3
EXCERPT_COST = 2_600  # per hit: three hits stay well inside the gateway's 12,000 characters
MAX_SEARCH_DOCS = 10

GONE = "An attached file is no longer available. Attach it again."
TRAINING_REFUSAL = (
    "This brain may learn from what it reads, so attached files are never shared with it. "
    "Switch to a private brain to use them."
)
NOT_HERE = "No attached file with that id in this conversation."


def _utcnow() -> datetime:
    return datetime.now(UTC)


class DocumentService:
    def __init__(
        self,
        store: AttachmentStore,
        *,
        limits: Limits | None = None,
        now: Callable[[], datetime] = _utcnow,
        max_running: int = MAX_RUNNING,
    ) -> None:
        self.store = store
        self.limits = limits or Limits()
        self._now = now
        self._max_running = max_running
        self._running = 0
        self._lock = threading.Lock()  # the count changes on worker threads too

    @property
    def running(self) -> int:
        return self._running

    # ---- upload ---------------------------------------------------------------------------

    async def upload(self, owner: str, name: str, data: bytes) -> AttachmentRef:
        clean = clean_name(name)
        kind = kind_for(clean)
        if len(data) > MAX_FILE_BYTES:
            raise too_large(len(data))
        sniff(data, kind)
        await self._room_for(owner)
        out = await self._extract(data, kind)
        chunks, cut = split(out.text, out.page_starts)
        kept = chunks[-1].start + len(chunks[-1].text) if cut else len(out.text)
        att = Attachment(
            id=new_doc_id(),
            owner=owner,
            name=clean,
            kind=kind,
            size=len(data),
            pages=out.pages,
            pages_total=out.pages_total,
            words=len(out.text[:kept].split()),
            chars=kept,
            chunk_count=len(chunks),
            truncated=out.truncated or cut,
            preview=out.text[:PREVIEW_CHARS],
            created_at=self._now(),
        )
        await self.store.create(att, chunks)
        log.info(  # never the name or the text: both may be private
            "document stored",
            extra={"kind": kind, "bytes": len(data), "chars": kept, "chunks": len(chunks)},
        )
        return att.ref()

    async def _sweep(self, owner: str) -> int:
        """Delete the owner's uploads never sent within a day; the number still waiting."""
        fresh = 0
        for a in await self.store.waiting():
            if a.owner != owner:
                continue
            if self._now() - a.created_at > WAITING_TTL:
                await self.store.delete(a.id)
            else:
                fresh += 1
        return fresh

    async def _room_for(self, owner: str) -> None:
        """Sweep the owner's stale waiting uploads, then refuse past the waiting cap."""
        if await self._sweep(owner) >= MAX_WAITING:
            raise DocumentRejected(
                "too_many",
                f"{MAX_WAITING} files are already waiting to be sent. Send or remove some first.",
                status=409,
            )

    async def _extract(self, data: bytes, kind: str) -> Extracted:
        with self._lock:
            if self._running >= self._max_running:
                raise DocumentRejected(
                    "busy",
                    "JARVIS is still reading other files. Try again in a minute.",
                    status=503,
                )
            self._running += 1

        def work() -> Extracted:
            try:
                return extract(data, kind, self.limits)
            finally:
                with self._lock:
                    self._running -= 1

        try:
            return await asyncio.wait_for(asyncio.to_thread(work), self.limits.budget_s + GRACE_S)
        except TimeoutError:
            log.warning("document extraction timed out", extra={"kind": kind})
            raise DocumentRejected(
                "too_slow",
                "This file took too long to read. Try a smaller file, or save it as text.",
            ) from None

    async def discard(self, owner: str, aid: str) -> None:
        """The owner removed a file before sending it."""
        a = await self.store.get(aid)
        if a is None or a.owner != owner or not a.waiting:
            raise DocumentRejected("not_found", "That file is not waiting to be sent.", status=404)
        await self.store.delete(aid)

    # ---- sending --------------------------------------------------------------------------

    async def check(self, owner: str, ids: Sequence[str], spec: BrainSpec) -> list[Attachment]:
        """Read-only: would these files go with a message to `spec`? (Raises InputRejected.)"""
        if not ids:
            return []
        if not spec.tools_allowed:
            raise InputRejected(TRAINING_REFUSAL)
        unique = list(dict.fromkeys(ids))
        if len(unique) > MAX_FILES_PER_MESSAGE:
            raise InputRejected(f"At most {MAX_FILES_PER_MESSAGE} files per message.")
        found = [await self.store.get(aid) for aid in unique]
        atts = [a for a in found if a is not None and a.owner == owner and a.waiting]
        if len(atts) != len(unique):
            raise InputRejected(GONE)
        return atts

    async def attach(
        self, turn: Turn, owner: str, session_id: str, ids: Sequence[str], spec: BrainSpec
    ) -> Turn:
        """`turn` with the files bound to this conversation and their note as a second block."""
        atts = await self.check(owner, ids, spec)
        if not atts:
            return turn
        try:
            bound = await self.store.bind(
                [a.id for a in atts], owner=owner, session_id=session_id, turn_id=turn.id
            )
        except NotAvailable:
            raise InputRejected(GONE) from None
        blocks = [TextBlock(text=turn.content), TextBlock(text=render_note(bound))]
        return turn.model_copy(update={"attachments": [a.ref() for a in bound], "blocks": blocks})

    async def forget_session(self, owner: str, session_id: str) -> int:
        """The conversation's files (and the owner's stale never-sent uploads, while at it)."""
        gone = 0
        for a in await self.store.in_session(session_id):
            if a.owner == owner:
                await self.store.delete(a.id)
                gone += 1
        await self._sweep(owner)
        return gone

    # ---- reading (the tools) ----------------------------------------------------------------

    async def _usable(self, owner: str, session_id: str | None, aid: str) -> Attachment:
        a = await self.store.get(aid)
        if a is None or not session_id or a.owner != owner or a.session != session_id:
            raise LookupError(NOT_HERE)
        if a.waiting:
            raise LookupError(NOT_HERE)
        return a

    async def read_part(
        self, owner: str, session_id: str | None, aid: str, part: int
    ) -> dict[str, Any]:
        a = await self._usable(owner, session_id, aid)
        if not 1 <= part <= a.parts:
            raise ValueError(f"part must be 1-{a.parts} for this file")
        chunks = (await self.store.chunks(a))[(part - 1) * CHUNKS_PER_PART : part * CHUNKS_PER_PART]
        if not chunks:
            raise LookupError(NOT_HERE)
        pages = pages_label(chunks[0].page, chunks[-1].page_end)
        source = f"attached file “{a.name}”, part {part} of {a.parts}"
        return {
            "doc_id": a.id,
            "name": a.name,
            "part": part,
            "parts": a.parts,
            "pages": pages,
            "more": part < a.parts,
            "text": wrap_external(
                "".join(c.text for c in chunks).strip(),
                source=source + (f", {pages}" if pages else ""),
            ),
        }

    async def search(
        self, owner: str, session_id: str | None, aid: str | None, query: str
    ) -> dict[str, Any]:
        if aid:
            targets = [await self._usable(owner, session_id, aid)]
        elif session_id:
            here = await self.store.in_session(session_id)
            targets = [a for a in here if a.owner == owner and not a.waiting]
            targets = sorted(targets, key=lambda a: a.created_at, reverse=True)[:MAX_SEARCH_DOCS]
        else:
            targets = []
        if not targets:
            return {
                "query": query,
                "hits": [],
                "note": "No files are attached in this conversation.",
            }
        found: list[tuple[float, Attachment, int, Any]] = []
        for a in targets:
            chunks = await self.store.chunks(a)
            for i, score in rank([c.text for c in chunks], query)[:TOP_HITS]:
                found.append((score, a, i, chunks[i]))
        found.sort(key=lambda f: -f[0])
        hits = []
        for _, a, i, c in found[:TOP_HITS]:
            part = i // CHUNKS_PER_PART + 1
            pages = pages_label(c.page, c.page_end)
            source = f"attached file “{a.name}”, part {part}" + (f", {pages}" if pages else "")
            text = wrap_external(excerpt(c.text.strip(), query, EXCERPT_COST), source=source)
            hits.append(
                {"doc_id": a.id, "name": a.name, "part": part, "pages": pages, "text": text}
            )
        note = (
            "Passages ranked by shared words; read a whole part with doc_read."
            if hits
            else "No passage matched those words. Try other words, or read parts with doc_read."
        )
        return {"query": query, "hits": hits, "note": note}


# ---- the Brain's hooks (one line each there; brain.py stays within its size budget) ------------


def files_of(docs: DocumentService | None) -> DocumentService:
    """The service, or the plain refusal a message with files gets when documents are off."""
    if docs is None:
        raise InputRejected("Attached files are not available on this server.")
    return docs


async def precheck(docs: DocumentService | None, req: ChatRequest, spec: BrainSpec) -> None:
    """Before a NEW conversation is created: a refused file must not leave an empty one."""
    if req.attachments:
        await files_of(docs).check(req.user_id, req.attachments, spec)


async def with_files(
    docs: DocumentService | None, turn: Turn, req: ChatRequest, spec: BrainSpec, session_id: str
) -> Turn:
    """The owner's turn, with the files sent with `req` bound to the conversation and noted."""
    if not req.attachments:
        return turn
    return await files_of(docs).attach(turn, req.user_id, session_id, req.attachments, spec)


async def forget_files(docs: DocumentService | None, owner: str, session_id: str) -> None:
    """The conversation is being deleted: its files go first, so none outlives it."""
    if docs is not None:
        await docs.forget_session(owner, session_id)


def too_large(size: int | None = None) -> DocumentRejected:
    limit = f"the limit is {MAX_FILE_BYTES // (1024 * 1024)} MB per file"
    said = f"That file is {size / (1024 * 1024):.1f} MB; " if size else "That file is too big: "
    return DocumentRejected("too_large", said + limit + ".", status=413)


__all__ = [
    "DocumentService",
    "files_of",
    "forget_files",
    "precheck",
    "too_large",
    "with_files",
]
