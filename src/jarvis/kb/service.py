# src/jarvis/kb/service.py
"""The notes service (R2 D10, D8; Layer 3 over the encrypted store).

add / update   cleaned and checked by `models.clean_fields`; the origin (trust) is decided by the
               caller from what it knows of the round, never from a client.
get / search / browse
               reads; search is deterministic (`kb.search`), no model call.
remove         a soft delete: a generic entry in Recently deleted first (no copy, no delete),
               then the note gets `deleted_at`; a failed tombstone drops the entry again.
restore        the bin's Restorer: clears the tombstone in place (same id). A note that comes
               back from an entry that was not the owner's own words is marked `outside`.
purge          the bin's Purger: hard-deletes a tombstoned note; safe to repeat; never touches a
               note that was restored.
fetch          the owner's click: page text through `kb.fetch` (1 web credit), at most 10 an hour.
export / import_ / wipe
               the owner's JSON file (live notes only; the sensitive filter applies on the way in)
               and the privacy dashboard's delete.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from jarvis.config import Settings
from jarvis.kb.fetch import fetch_page
from jarvis.kb.models import (
    MAX_EXCERPT,
    MAX_LIVE,
    MAX_PAGE_TITLE,
    MSG_FULL,
    NOTE_ID,
    PAGE_SIZE,
    ImportResult,
    Note,
    NotesError,
    NotesPage,
    NoteView,
    PageExcerpt,
    check_sensitive,
    clean_fields,
    invalid,
    not_found,
    vouches,
    worse_origin,
)
from jarvis.kb.search import Hit, rank
from jarvis.kb.store import NotesStore
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.storage.docs import Docs
from jarvis.tools.external import clean_text, model_text
from jarvis.undo.models import DeletedItem
from jarvis.undo.service import (
    Gone,
    Restored,
    SnapshotFailed,
    StillThere,
    UndoBin,
    discard_kind,
)
from jarvis.web.service import WebService

log = get_logger(__name__)

FETCH_PER_HOUR = 10
HOUR_S = 3600.0
EXPORT_FORMAT = "jarvis-notes"
EXPORT_VERSION = 1
EXPORT_SIGN_TAG = "jarvis-notes-export/v1"
KIND_WORD = {"note": "note", "memo": "memo", "link": "link"}
NOT_CONFIGURED = "Notes are not available on this server (no encryption key)."


def utcnow() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return f"n_{secrets.token_hex(6)}"


def _live_count(notes: tuple[Note, ...]) -> int:
    return sum(1 for n in notes if n.live)


def _bin_title(note: Note) -> str:
    """Generic: the bin's title is stored in clear, so it never carries the owner's words."""
    at = note.created_at
    return f"A {KIND_WORD[note.kind]} from {at.day} {at:%b}"


class NotesService:
    def __init__(
        self,
        store: NotesStore,
        *,
        web: WebService | None = None,
        undo: UndoBin | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.store = store
        self.web = web
        self.undo = undo
        self._clock = clock

    # ---- writing --------------------------------------------------------------------------------

    async def add(
        self,
        uid: str,
        *,
        kind: str,
        text: object = "",
        title: object = None,
        tags: Any = None,
        url: object = None,
        owner_note: object = "",
        origin: str = "typed",
    ) -> Note:
        f = clean_fields(
            kind=kind, text=text, title=title, tags=tags, url=url, owner_note=owner_note
        )
        now = self._clock()
        note = Note(
            id=_new_id(),
            kind=kind,  # type: ignore[arg-type]
            title=f.title,
            text=f.text,
            tags=f.tags,
            origin=origin,  # type: ignore[arg-type]
            created_at=now,
            updated_at=now,
            url=f.url,
            owner_note=f.owner_note,
        )

        def fn(cur: tuple[Note, ...]) -> tuple[tuple[Note, ...], Note]:
            if _live_count(cur) >= MAX_LIVE:
                raise NotesError(409, "notes_full", MSG_FULL)
            return (*cur, note), note

        return (await self.store.change(uid, fn))[1]

    async def update(
        self,
        uid: str,
        note_id: str,
        *,
        text: object = None,
        title: object = None,
        tags: Any = None,
        owner_note: object = None,
        origin: str = "typed",
        adopt: bool = False,
    ) -> Note:
        """Change a live note. `None` leaves a field as it is. An edit never makes a note more
        trusted by itself: a voice or outside note stays so. Only `adopt=True` (the console, where
        the owner read the whole text and ticked "mark as mine") makes it his own."""
        self._id(note_id)

        def fn(cur: tuple[Note, ...]) -> tuple[tuple[Note, ...], Note]:
            old = _find(cur, note_id)
            f = clean_fields(
                kind=old.kind,
                text=old.text if text is None else text,
                title=old.title if title is None else title,
                tags=old.tags if tags is None else tags,
                url=old.url,
                owner_note=old.owner_note if owner_note is None else owner_note,
            )
            new_origin = worse_origin(old.origin, origin)
            if adopt and old.page is None:
                new_origin = "typed"
            new = old.model_copy(
                update={
                    "title": f.title,
                    "text": f.text,
                    "tags": f.tags,
                    "owner_note": f.owner_note,
                    "origin": new_origin,
                    "updated_at": self._clock(),
                }
            )
            return tuple(new if n.id == note_id else n for n in cur), new

        return (await self.store.change(uid, fn))[1]

    # ---- reading --------------------------------------------------------------------------------

    @staticmethod
    def _id(note_id: object) -> str:
        if not isinstance(note_id, str) or not NOTE_ID.fullmatch(note_id):
            raise not_found()
        return note_id

    async def get(self, uid: str, note_id: str) -> Note:
        self._id(note_id)
        return _find((await self.store.load(uid)).notes, note_id)

    async def search(self, uid: str, query: str, *, kind: str | None = None) -> list[Hit]:
        notes = (await self.store.load(uid)).notes
        return rank(notes, query, self._clock(), kind=kind)

    async def browse(
        self, uid: str, *, q: str = "", kind: str | None = None, page: int = 1
    ) -> NotesPage:
        notes = (await self.store.load(uid)).notes
        live = [n for n in notes if n.live]
        counts = {k: sum(1 for n in live if n.kind == k) for k in ("note", "memo", "link")}
        if q.strip():
            hits = rank(notes, q, self._clock(), kind=kind)
            items = [NoteView.of(h.note, h.snippet) for h in hits]
            return NotesPage(items=items, total=len(items), page=1, pages=1, counts=counts)
        rows = sorted(
            (n for n in live if kind is None or n.kind == kind),
            key=lambda n: (n.updated_at, n.id),
            reverse=True,
        )
        pages = max(1, -(-len(rows) // PAGE_SIZE))
        page = min(max(1, page), pages)
        chunk = rows[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
        return NotesPage(
            items=[NoteView.of(n) for n in chunk],
            total=len(rows),
            page=page,
            pages=pages,
            counts=counts,
        )

    async def counts(self, uid: str) -> dict[str, int]:
        return (await self.store.summary(uid))[1]

    # ---- delete, restore, purge -----------------------------------------------------------------

    async def remove(
        self, uid: str, note_id: str, *, session_id: str | None = None, trace_id: str | None = None
    ) -> DeletedItem:
        self._id(note_id)
        note = _find((await self.store.load(uid)).notes, note_id)
        if self.undo is None:
            raise NotesError(
                503, "undo_unavailable", "Recently deleted isn't available, so nothing was deleted."
            )
        try:
            item = await self.undo.keep(
                uid,
                "note",
                _bin_title(note),
                {"ref": note_id},
                owner_authored=vouches(note),
                session_id=session_id,
                trace_id=trace_id,
            )
        except SnapshotFailed as exc:
            raise NotesError(503, "undo_unavailable", str(exc)) from None
        now = item.deleted_at  # the tombstone carries its bin entry's time: purge matches on it

        def fn(cur: tuple[Note, ...]) -> tuple[tuple[Note, ...], None]:
            old = _find(cur, note_id)
            gone = old.model_copy(update={"deleted_at": now, "updated_at": now})
            return tuple(gone if n.id == note_id else n for n in cur), None

        try:
            await self.store.change(uid, fn)
        except Exception:
            await self.undo.discard(uid, item.id)
            raise
        return item

    @staticmethod
    def _ref(item: DeletedItem) -> str:
        ref = item.snapshot.get("ref") if isinstance(item.snapshot, dict) else None
        if not isinstance(ref, str) or not NOTE_ID.fullmatch(ref):
            raise Gone()
        return ref

    async def restore(self, uid: str, item: DeletedItem, *, outside: bool = False) -> Restored:
        """Restorer (the bin calls it): clear the tombstone in place; same id. A note removed for
        good (purged, or the privacy dashboard wiped the notes) is `Gone`."""
        ref = self._ref(item)

        def fn(cur: tuple[Note, ...]) -> tuple[tuple[Note, ...], None]:
            found = next((n for n in cur if n.id == ref), None)
            if found is None:
                raise Gone()
            if found.live:
                raise StillThere("That note is still there; nothing was restored.")
            if _live_count(cur) >= MAX_LIVE:
                raise NotesError(409, "notes_full", MSG_FULL)
            origin = worse_origin(found.origin, "outside") if outside else found.origin
            back = found.model_copy(
                update={"deleted_at": None, "origin": origin, "updated_at": self._clock()}
            )
            return tuple(back if n.id == ref else n for n in cur), None

        await self.store.change(uid, fn)
        return Restored(new_id=ref)

    async def purge(self, uid: str, item: DeletedItem) -> None:
        """Purger: hard-delete the tombstoned note (idempotent; a restored note is left alone)."""
        ref = self._ref(item)
        if item.restored:
            return

        def fn(cur: tuple[Note, ...]) -> tuple[tuple[Note, ...], None]:
            found = next((n for n in cur if n.id == ref), None)
            if found is None or found.live or found.deleted_at != item.deleted_at:
                return cur, None  # restored, or deleted again by a later bin entry: not ours
            return tuple(n for n in cur if n.id != ref), None

        await self.store.change(uid, fn)

    # ---- fetching a link's page -----------------------------------------------------------------

    async def _take_fetch_slot(self, uid: str) -> float:
        now = self._clock().timestamp()
        if not await self.store.take_fetch_slot(uid, now, FETCH_PER_HOUR, HOUR_S):
            raise NotesError(
                429, "rate_limited", f"At most {FETCH_PER_HOUR} page fetches an hour. Try later."
            )
        return now

    async def fetch(self, uid: str, note_id: str) -> Note:
        note = await self.get(uid, note_id)  # live first: a deleted note reserves nothing
        if note.kind != "link" or not note.url:
            raise invalid("Only a saved link has a page to fetch.")
        slot = await self._take_fetch_slot(uid)
        try:
            got = await fetch_page(self.web, note.url)
            page = PageExcerpt(title=got.title, excerpt=got.excerpt, fetched_at=self._clock())

            def fn(cur: tuple[Note, ...]) -> tuple[tuple[Note, ...], Note]:
                old = _find(cur, note_id)
                new = old.model_copy(update={"page": page, "updated_at": self._clock()})
                return tuple(new if n.id == note_id else n for n in cur), new

            return (await self.store.change(uid, fn))[1]
        except BaseException:
            await self.store.give_back_fetch_slot(uid, slot)  # nothing was fetched or kept
            raise

    # ---- export, import, wipe -------------------------------------------------------------------

    @staticmethod
    def _signed_text(uid: str, notes: object) -> str:
        """What the export signature covers: a domain tag (the notes key is shared with the
        encryption purpose), the owner, and the canonical JSON of the notes."""
        body = json.dumps(notes, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return f"{EXPORT_SIGN_TAG}\n{uid}\n{body}"

    async def export(self, uid: str) -> dict[str, Any]:
        live = [n for n in (await self.store.load(uid)).notes if n.live]
        notes = [n.model_dump(mode="json", exclude={"deleted_at"}) for n in live]
        return {
            "format": EXPORT_FORMAT,
            "version": EXPORT_VERSION,
            "exported_at": self._clock().isoformat(),
            "notes": notes,
            "signature": self.store.mac(self._signed_text(uid, notes)),
        }

    async def import_(self, uid: str, data: object) -> ImportResult:
        """Add the notes of an export. Each is checked like a new note (the sensitive filter,
        lengths, the link); a duplicate id, a deleted note or anything odd is skipped. A file
        whose signature checks (this owner's own export, unchanged) keeps each note's trust; any
        other file is outside content, so every note in it is `outside`."""
        raw = _export_notes(data)
        sig = data.get("signature") if isinstance(data, dict) else None
        signed = self.store.mac_matches(self._signed_text(uid, raw), sig)
        done, skipped = await asyncio.to_thread(self._clean_all, raw, signed)

        def fn(cur: tuple[Note, ...]) -> tuple[tuple[Note, ...], int]:
            have = {n.id for n in cur}
            room = MAX_LIVE - _live_count(cur)
            added: list[Note] = []
            for n in done:
                if n.id in have or len(added) >= room:
                    continue
                have.add(n.id)
                added.append(n)
            return (*cur, *added), len(added)

        count = (await self.store.change(uid, fn))[1]
        return ImportResult(added=count, skipped=len(raw) - count)

    def _clean_all(self, raw: list[Any], signed: bool) -> tuple[list[Note], int]:
        done: list[Note] = []
        skipped = 0
        for item in raw:
            note = self._importable(item, signed)
            if note is None:
                skipped += 1
            else:
                done.append(note)
        return done, skipped

    def _importable(self, item: object, signed: bool) -> Note | None:
        if not isinstance(item, dict):
            return None
        try:
            note = Note.model_validate({**item, "deleted_at": None})
            f = clean_fields(
                kind=note.kind,
                text=note.text,
                title=note.title,
                tags=list(note.tags),
                url=note.url,
                owner_note=note.owner_note,
            )
        except (ValidationError, NotesError, ValueError, TypeError):
            return None
        page = note.page
        if page is not None:
            page = PageExcerpt(
                title=model_text(clean_text(page.title))[:MAX_PAGE_TITLE],
                excerpt=model_text(clean_text(page.excerpt))[:MAX_EXCERPT],
                fetched_at=page.fetched_at,
            )
        nid = note.id if NOTE_ID.fullmatch(note.id) else _new_id()
        return note.model_copy(
            update={
                "id": nid,
                "origin": worse_origin(note.origin, "imported") if signed else "outside",
                "title": f.title,
                "text": f.text,
                "tags": f.tags,
                "url": f.url,
                "owner_note": f.owner_note,
                "page": page,
            }
        )

    async def wipe(self, uid: str) -> int:
        """Delete every note of this owner (the privacy dashboard), and their entries in Recently
        deleted (R2 review H2: nothing could restore them); returns the live ones."""
        count = await self.store.wipe(uid)
        await discard_kind(self.undo, uid, "note")
        return count


def _find(notes: tuple[Note, ...], note_id: str) -> Note:
    for n in notes:
        if n.id == note_id and n.live:
            return n
    raise not_found()


def _export_notes(data: object) -> list[Any]:
    if (
        not isinstance(data, dict)
        or data.get("format") != EXPORT_FORMAT
        or not isinstance(data.get("notes"), list)
    ):
        raise invalid("The file is not a JARVIS notes export.")
    notes: list[Any] = data["notes"]
    if len(notes) > MAX_LIVE:
        raise invalid(f"An import holds at most {MAX_LIVE:,} notes.")
    return notes


def build_notes_service(
    s: Settings, docs: Docs, *, web: WebService | None, undo: UndoBin | None
) -> NotesService | None:
    """None (notes OFF, never stored in clear) when switched off or there is no token key."""
    if not s.notes_enabled:
        return None
    keyring = Keyring.from_settings(s)
    if keyring is None:
        return None
    return NotesService(NotesStore(docs, keyring, prefix=s.firestore_prefix), web=web, undo=undo)


__all__ = [
    "EXPORT_FORMAT",
    "FETCH_PER_HOUR",
    "NOT_CONFIGURED",
    "NotesService",
    "build_notes_service",
    "check_sensitive",
]
