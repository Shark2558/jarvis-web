# src/jarvis/documents/service.py
"""Attached documents, end to end (slice 10 E; Layer 2 input → 7 data → 5 skill).

upload   name → type (extension + magic bytes) → text from a killable child process with CPU,
         memory and wall-clock limits (`isolation`; one at a time across the app — Drive files
         use the same `extract` — others queue ≤ 50 s, then "busy") → chunks → one commit.
         The file itself is dropped. Waiting uploads: ≤ 10 per
         owner; older than a day → swept at the next upload, a conversation delete, and the
         scheduler tick (`sweep_waiting`, at most hourly).
switched off  Documents on "Never" in Permissions refuses uploads and sending (integration
         review), and an unreadable setting refuses too — no file's start reaches the model.
attach   on send (inside the Brain's per-conversation lock): refused for a training brain;
         within what one message may carry (`AttachPolicy`, R11.1: 10 files, 40 MB together,
         4 pictures; the owner's settings); each must be the owner's and still waiting; bound
         atomically to the conversation and the turn; the turn gets a second text block
         (`render_note`). If the turn then can't be stored, the binding is undone
         (`save_owner_turn`).
kinds    R11.1 D10-D11: Excel, PowerPoint, zip, a folder (the console's one bundle; the upload
         says so) and pictures go through the same child. A picture is kept as cleaned bytes
         beside the file (`AttachmentStore.pictures`), never in a turn; `pictures_of_turn` hands
         them to `documents.pictures` for the turn they came with, and to nothing else. Which
         turn is the latest comes from the STORED conversation (`sessions`), never from this
         process (code review M3: several instances, restarts).
read / search (the doc_read / doc_search tools): only the owner's files, only in the
         conversation they were sent in. Text is fenced as external content. Ranking runs off
         the event loop; a search without an id covers the 3 most recent files.
forget_session  the owner deleted the conversation: its files go too (before the turns).
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from jarvis.core.guardrails import ActionRisk, InputRejected
from jarvis.core.models import ChatRequest, Session, Turn
from jarvis.core.saving import save_owner_message
from jarvis.documents.chunking import excerpt, pages_label, rank, split
from jarvis.documents.extract import Extracted, Limits, kind_for, sniff
from jarvis.documents.isolation import Sandbox, extract_isolated
from jarvis.documents.limits import ARCHIVE_KINDS, FOLDER
from jarvis.documents.models import (
    CHUNKS_PER_PART,
    MAX_FILE_BYTES,
    MAX_WAITING,
    PREVIEW_CHARS,
    Attachment,
    AttachmentRef,
    AttachPolicy,
    DocumentRejected,
    StoredPicture,
    new_doc_id,
)
from jarvis.documents.note import clean_name, render_note
from jarvis.documents.store import AttachmentStore, NotAvailable
from jarvis.llm.base import TextBlock
from jarvis.llm.brains import BrainSpec
from jarvis.logging import get_logger
from jarvis.memory.base import SessionStore
from jarvis.tools.external import wrap_external
from jarvis.tools.policy import Effect, OwnerRules

log = get_logger(__name__)

QUEUE_WAIT_S = 50.0  # one child at a time; a queued upload gives up after this ("busy")
WAITING_TTL = timedelta(hours=24)
SWEEP_EVERY = timedelta(hours=1)  # the scheduler tick's sweep of unsent uploads
TOP_HITS = 3
EXCERPT_COST = 2_600  # per hit: three hits stay well inside the gateway's 12,000 characters
# After the fence-like text in it is replaced by a (longer) notice, the fenced text is cut to
# these, so a part or a search answer always fits the gateway's cut and its fence closes.
PART_TEXT_LIMIT = 10_000
EXCERPT_LIMIT = 3_000
MAX_SEARCH_DOCS = 3  # a search without an id: the most recent files of the conversation

GONE = "An attached file is no longer available. Attach it again."
TRAINING_REFUSAL = (
    "This brain may learn from what it reads, so attached files are never shared with it. "
    "Switch to a private brain to use them."
)
NOT_HERE = "No attached file with that id in this conversation."
NO_TEXT_IN_PICTURE = (
    "That file is a picture: it has no text to read. A brain that can see was shown it with the "
    "message it came with."
)
MB = 1024 * 1024
SWITCHED_OFF = "Documents are switched off in Permissions."
UNCHECKED = "JARVIS couldn't check your Permissions just now, so no file was used. Try again."
DOC_TOOLS = ("doc_read", "doc_search")  # the Documents permission group's tools


def _utcnow() -> datetime:
    return datetime.now(UTC)


def policy_from(s: Any) -> AttachPolicy:
    """What one message may carry, from the owner's settings (`Settings.attach_*`)."""
    return AttachPolicy(
        max_files=int(s.attach_max_files),
        total_bytes=int(s.attach_total_mb) * MB,
        zip_max_files=int(s.attach_zip_max_files),
        folder_max_files=int(s.attach_folder_max_files),
        picture_max_bytes=int(s.attach_picture_max_kb) * 1024,
    )


class DocumentService:
    def __init__(
        self,
        store: AttachmentStore,
        *,
        limits: Limits | None = None,
        now: Callable[[], datetime] = _utcnow,
        sandbox: Sandbox | None = None,
        queue_wait_s: float = QUEUE_WAIT_S,
        policy: AttachPolicy | None = None,
        sessions: SessionStore | None = None,
    ) -> None:
        self.store = store
        self.limits = limits or Limits()
        # R11.1: what one message may carry. The defaults are the settings' defaults; the app
        # gives the owner's own values when it builds the service (`policy_from`; R11.1 I1).
        self.policy = policy or AttachPolicy()
        # R11.1 D10: the conversations, read to know a conversation's latest owner turn (the app
        # passes `app.state.store`; INTEGRATION-B "Needs I1")
        self._sessions = sessions
        self.sandbox = sandbox or Sandbox()
        self._now = now
        self._queue_wait_s = queue_wait_s
        self._slot = asyncio.Semaphore(1)  # one extraction child at a time
        self._swept_at: datetime | None = None
        # the owner's Allow / Ask first / Never rules (slice 10 D; the app sets it): "Never" for
        # Documents refuses uploads and sending, so no file's start ever reaches the model
        self.rules: OwnerRules | None = None

    @property
    def running(self) -> int:
        return 1 if self._slot.locked() else 0

    @property
    def sessions(self) -> SessionStore | None:
        """The stored conversations (None: not given, so a turn's pictures cannot be found)."""
        return self._sessions

    # ---- the owner's Documents permission ---------------------------------------------------

    async def _switched_off(self, owner: str) -> bool:
        """Is Documents on "Never" for `owner`? Raises when the rules can't be read."""
        if self.rules is None:
            return False
        rules = await self.rules.rules_for(owner)
        return any(
            r.effect is Effect.DENY and r.matches(t, {}, ActionRisk.READ_ONLY)
            for r in rules
            for t in DOC_TOOLS
        )

    async def _off_problem(self, owner: str) -> str:
        """Why files may not be taken in or sent now ("" when they may). Fails closed."""
        try:
            return SWITCHED_OFF if await self._switched_off(owner) else ""
        except Exception as exc:  # noqa: BLE001 — refused, never raised as a server error
            log.warning("owner permissions unreadable", extra={"reason": type(exc).__name__})
            return UNCHECKED

    async def files_allowed(self, owner: str) -> bool:
        """May the owner's files be used at all (Documents not on "Never")? False when the
        setting cannot be read (fails closed): e.g. no file name becomes a speech hint."""
        return not await self._off_problem(owner)

    async def ensure_on(self, owner: str) -> None:
        """Upload: refused (403) when the owner switched Documents off; 503 when unreadable."""
        problem = await self._off_problem(owner)
        if problem == SWITCHED_OFF:
            raise DocumentRejected("documents_off", problem, status=403)
        if problem:
            raise DocumentRejected("permissions_unavailable", problem, status=503)

    # ---- upload ---------------------------------------------------------------------------

    def _limits_for(self, kind: str) -> Limits:
        """The child's limits for one upload, with the owner's caps for archives and pictures."""
        p = self.policy
        files = p.folder_max_files if kind == FOLDER else p.zip_max_files
        return dataclasses.replace(
            self.limits,
            archive_max_files=files,
            archive_max_total=p.total_bytes,
            picture_max_bytes=p.picture_max_bytes,
            max_pictures=p.max_pictures,
        )

    def _header(
        self,
        owner: str,
        name: str,
        kind: str,
        size: int,
        out: Extracted,
        kept: int,
        chunk_count: int,
        cut: bool,
        pictures: int,
    ) -> Attachment:
        """The stored header of a file just read: whose it is, what it holds, how much was kept."""
        return Attachment(
            id=new_doc_id(),
            owner=owner,
            waiting_owner=owner,
            name=name,
            kind=kind,
            size=size,
            pages=out.pages,
            pages_total=out.pages_total,
            words=len(out.text[:kept].split()),
            chars=kept,
            chunk_count=chunk_count,
            truncated=out.truncated or cut,
            preview=out.text[:PREVIEW_CHARS],
            created_at=self._now(),
            sheets=out.sheets,
            rows=out.rows,
            slides=out.slides,
            files=out.files if kind in ARCHIVE_KINDS else None,
            skipped=out.skipped,
            pictures=pictures,
        )

    async def upload(
        self, owner: str, name: str, data: bytes, *, folder: bool = False
    ) -> AttachmentRef:
        """`folder`: the console packed a folder's readable files into this one bundle (D11);
        its name is the folder's and has no extension."""
        clean = clean_name(name)
        kind = FOLDER if folder else kind_for(clean)
        await self.ensure_on(owner)
        if len(data) > MAX_FILE_BYTES:
            raise too_large(len(data))
        sniff(data, kind)
        await self._room_for(owner)
        out = await self.extract(data, kind, limits=self._limits_for(kind))
        chunks, cut = split(out.text, out.page_starts)
        kept = chunks[-1].start + len(chunks[-1].text) if cut else len(out.text)
        shots = [
            StoredPicture(name=p.name or clean, media_type=p.media_type, data=p.data)
            for p in out.pictures[: self.policy.max_pictures]
        ]
        att = self._header(owner, clean, kind, len(data), out, kept, len(chunks), cut, len(shots))
        await self.store.create(att, chunks, shots)
        log.info(  # never the name or the text: both may be private
            "document stored",
            extra={
                "kind": kind,
                "bytes": len(data),
                "chars": kept,
                "chunks": len(chunks),
                "pictures": len(shots),
            },
        )
        return att.ref()

    async def _sweep(self, owner: str | None) -> int:
        """Delete uploads never sent within a day (the owner's, or everyone's for None); the
        number of the owner's still waiting."""
        fresh = 0
        for a in await self.store.waiting():
            if owner is not None and a.owner != owner:
                continue
            if self._now() - a.created_at > WAITING_TTL:
                await self.store.delete(a.id)
            else:
                fresh += 1
        return fresh

    async def sweep_waiting(self) -> bool:
        """The scheduler tick: every owner's stale unsent uploads, at most once an hour.
        Never raises (a storage hiccup waits for the next tick). True when it ran."""
        now = self._now()
        if self._swept_at is not None and now - self._swept_at < SWEEP_EVERY:
            return False
        self._swept_at = now
        try:
            await self._sweep(None)
        except Exception as exc:  # noqa: BLE001 — the tick's other work must go on
            log.warning("unsent upload sweep failed", extra={"reason": type(exc).__name__})
        return True

    async def _room_for(self, owner: str) -> None:
        """Sweep the owner's stale waiting uploads, then refuse past the waiting cap (never
        fewer than one message may carry: R11.1 `attach_max_files`)."""
        cap = max(MAX_WAITING, self.policy.max_files)
        if await self._sweep(owner) >= cap:
            raise DocumentRejected(
                "too_many",
                f"{cap} files are already waiting to be sent. Send or remove some first.",
                status=409,
            )

    async def extract(self, data: bytes, kind: str, *, limits: Limits | None = None) -> Extracted:
        """The app's ONE extraction door: chat uploads and Drive files (slice 12 D1, injected
        into `DriveService` by the app) share this slot and sandbox, so two children never run
        at once on the 512 MiB instance. One child process at a time; the slot is released on
        every exit, cancellation included, and `extract_isolated` kills its child on every exit
        too. Raises `DocumentRejected` (slice 10's words; callers may re-word them)."""
        try:
            await asyncio.wait_for(self._slot.acquire(), self._queue_wait_s)
        except TimeoutError:
            raise DocumentRejected(
                "busy", "JARVIS is still reading other files. Try again in a minute.", status=503
            ) from None
        try:
            return await extract_isolated(data, kind, limits or self.limits, self.sandbox)
        finally:
            self._slot.release()

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
        if problem := await self._off_problem(owner):
            raise InputRejected(problem)  # nothing bound: the files stay waiting
        if not spec.tools_allowed:
            raise InputRejected(TRAINING_REFUSAL)
        unique = list(dict.fromkeys(ids))
        if len(unique) > self.policy.max_files:
            raise InputRejected(f"At most {self.policy.max_files} files per message.")
        found = [await self.store.get(aid) for aid in unique]
        atts = [a for a in found if a is not None and a.owner == owner and a.waiting]
        if len(atts) != len(unique):
            raise InputRejected(GONE)
        self._within_policy(atts)
        return atts

    def _within_policy(self, atts: Sequence[Attachment]) -> None:
        """R11.1 D10-D11: the files of one message together, and its pictures."""
        p = self.policy
        total = sum(a.size for a in atts)
        if total > p.total_bytes:
            raise InputRejected(
                f"These files are {total / MB:.1f} MB together; the limit is "
                f"{p.total_bytes / MB:.0f} MB per message. Send some of them in another message."
            )
        if sum(a.pictures for a in atts) > p.max_pictures:
            raise InputRejected(f"At most {p.max_pictures} pictures per message.")

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
        if a.chunk_count == 0 and a.pictures:
            raise ValueError(NO_TEXT_IN_PICTURE)
        if not 1 <= part <= a.parts:
            raise ValueError(f"part must be 1-{a.parts} for this file")
        first = (part - 1) * CHUNKS_PER_PART
        chunks = await self.store.part(a, first, first + CHUNKS_PER_PART)  # only this part's
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
                limit=PART_TEXT_LIMIT,
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
            # tokenising ~300,000 characters takes a while: keep it off the event loop
            ranked = await asyncio.to_thread(rank, [c.text for c in chunks], query)
            for i, score in ranked[:TOP_HITS]:
                found.append((score, a, i, chunks[i]))
        found.sort(key=lambda f: -f[0])
        hits = []
        for _, a, i, c in found[:TOP_HITS]:
            part = i // CHUNKS_PER_PART + 1
            pages = pages_label(c.page, c.page_end)
            source = f"attached file “{a.name}”, part {part}" + (f", {pages}" if pages else "")
            text = wrap_external(
                excerpt(c.text.strip(), query, EXCERPT_COST), source=source, limit=EXCERPT_LIMIT
            )
            hits.append(
                {"doc_id": a.id, "name": a.name, "part": part, "pages": pages, "text": text}
            )
        note = (
            "Passages ranked by shared words; read a whole part with doc_read."
            if hits
            else "No passage matched those words. Try other words, or read parts with doc_read."
        )
        return {"query": query, "hits": hits, "note": note}

    # ---- pictures (R11.1 D10): only for the turn they came with -------------------------------

    async def pictures_of_turn(
        self, owner: str, session_id: str, turn: Turn
    ) -> list[StoredPicture]:
        """The cleaned pictures of the files sent with exactly this turn, in the order they were
        attached; at most `policy.max_pictures`. The turn names its files; each is read again
        through the document store and must be the owner's, in this conversation, bound to this
        turn. Storage errors are raised (the caller tells them from "no picture")."""
        out: list[StoredPicture] = []
        found = [await self.store.get(ref.id) for ref in turn.attachments if ref.pictures]
        mine = [
            a
            for a in found
            if a is not None
            and a.owner == owner
            and a.session == session_id
            and a.turn == turn.id
            and a.pictures
        ]
        for a in sorted(mine, key=lambda a: (a.created_at, a.id)):
            out += await self.store.pictures(a)
        return out[: self.policy.max_pictures]


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


async def save_owner_turn(
    docs: DocumentService | None,
    store: SessionStore,
    session: Session,
    turn: Turn,
    req: ChatRequest,
    spec: BrainSpec,
) -> None:
    """Append the owner's turn — with the files sent with `req` bound to this conversation and
    noted — and store it before any model call. If storing fails the binding is undone, so the
    files are still waiting and can be sent again (never bound to a turn that doesn't exist)."""
    if not req.attachments:
        session.append(turn)
        await save_owner_message(store, session)
        return
    svc = files_of(docs)
    noted = await svc.attach(turn, req.user_id, session.id, req.attachments, spec)
    session.append(noted)
    try:
        await save_owner_message(store, session)  # another window first: MessageNotSaved
    except Exception:
        ids = [a.id for a in noted.attachments]
        try:
            await svc.store.unbind(ids, owner=req.user_id, turn_id=turn.id)
        except Exception as exc:  # noqa: BLE001 — report the save failure, not this one
            log.error("could not undo a file binding", extra={"reason": type(exc).__name__})
        raise


async def forget_files(docs: DocumentService | None, owner: str, session_id: str) -> None:
    """The conversation is being deleted: its files go first, so none outlives it."""
    if docs is not None:
        await docs.forget_session(owner, session_id)


def too_large(size: int | None = None) -> DocumentRejected:
    limit = f"the limit is {MAX_FILE_BYTES // (1024 * 1024)} MB per file"
    said = f"That file is {size / (1024 * 1024):.1f} MB; " if size else "That file is too big: "
    return DocumentRejected("too_large", said + limit + ".", status=413)


__all__ = [
    "NO_TEXT_IN_PICTURE",
    "DocumentService",
    "files_of",
    "forget_files",
    "policy_from",
    "precheck",
    "save_owner_turn",
    "too_large",
]
