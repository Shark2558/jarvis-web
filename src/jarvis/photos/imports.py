# src/jarvis/photos/imports.py
"""A Google Photos import as a background, resumable job (R11.1 O6; plan D14).

    {prefix}photo_imports/{uid}   {session_id, state, total, done, faces, known, skipped, over,
                                   todo: [Google item ids still to do], list_token, cursor,
                                   wrapped, people: [fp_ ids recognised], paused, updated_at}

Ids and counts only: never a picture, a link or a name. `Importer.step` does ONE step and saves
after every photo, so a restart, a sleeping laptop or a step that runs out of time loses nothing:

1. the laptop first (one cheap call): asleep, or on a kit from before the photo routes, means
   nothing is downloaded for it and the import says why it is paused;
2. picking -> listing: Google's list is read a page at a time and only the item ids are kept
   (at most the owner's `photos_max_picked`; what was picked beyond it is counted, not imported);
3. reading: at most `photos_import_batch` photos, one at a time (download, metadata stripped by
   the Picker client, sent to the laptop, dropped). Google's download links expire, so each step
   asks for the page again and no link is ever kept; `cursor` remembers which page holds the
   next photo. Photos that are no longer in the pick are counted as "could not be read" after
   one whole pass of the list finds none of them;
4. a session Google has ended (404) stops the import cleanly: "pick again to continue", with
   what was done kept and the ids still to do dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol

from jarvis.faces.models import State
from jarvis.faces.ports import RECOGNITION_THRESHOLD, is_person_id
from jarvis.integrations.google import GoogleAPIError, GoogleNotConnected, GoogleNotFound
from jarvis.logging import get_logger
from jarvis.photos.edge import (
    READY,
    EdgeBadReply,
    EdgeNotReady,
    EdgeOffline,
    EdgeRefused,
    HomeEdge,
)
from jarvis.photos.errors import PickerError
from jarvis.photos.models import FaceHit, ImportLimits, PickedItem, PickerSession
from jarvis.photos.picker import PICKER_MAX, PhotosNotGranted
from jarvis.storage.docs import Delete, Docs, Set
from jarvis.undo.store import owner_ok

log = get_logger(__name__)

STATES = ("none", "picking", "listing", "reading", "done", "expired")
PAUSES = {
    "laptop": "laptop not reachable",
    "kit": "update the home kit on your laptop (Integrations -> Home)",
    "reader": "the face reader on your laptop isn't ready yet",
    "edge": "your laptop's answer couldn't be understood",
    "google": "Google Photos isn't answering",
}
MAX_PAGES_PER_STEP = 30
ID_MAX = 200
TOKEN_MAX = 2000
MAX_PEOPLE = 30
EXPIRED_WORDS = "the Google Photos session ended: pick again to continue"


class PickerPort(Protocol):
    async def create_session(self, uid: str, max_items: int | None = None) -> PickerSession: ...
    async def get_session(self, uid: str, session_id: str) -> PickerSession: ...
    async def list_page(
        self, uid: str, session_id: str, token: str = ""
    ) -> tuple[tuple[PickedItem, ...], str]: ...
    async def download(self, uid: str, item: PickedItem) -> bytes: ...
    async def delete_session(self, uid: str, session_id: str) -> None: ...


class RegistryPort(Protocol):
    async def state(self, uid: str) -> State: ...


@dataclass(frozen=True)
class ImportDoc:
    session_id: str = ""
    state: str = "none"
    total: int = 0
    done: int = 0
    faces: int = 0
    known: int = 0
    skipped: int = 0
    over: int = 0
    todo: tuple[str, ...] = ()
    list_token: str = ""
    cursor: str = ""
    wrapped: bool = False  # this pass of the list began at its first page and found nothing yet
    people: tuple[str, ...] = ()
    paused: str = ""

    @property
    def unknown(self) -> int:
        return max(0, self.faces - self.known)


@dataclass(frozen=True)
class StepOut:
    doc: ImportDoc
    unknown: tuple[str, ...] = ()  # unnamed cluster ids seen in this step
    picker_uri: str = ""  # still picking: Google's link again


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _text(value: object, limit: int) -> str:
    return value if isinstance(value, str) and len(value) <= limit else ""


def _plural(n: int, one: str, many: str) -> str:
    return f"{n:,} {one if n == 1 else many}"


def describe(doc: ImportDoc, limit: int = PICKER_MAX) -> str:
    """The import in plain words: "312 of 2,000 read · 41 faces found · paused: ..."."""
    pause = f"paused: {PAUSES[doc.paused]}" if doc.paused in PAUSES else ""
    if doc.state == "picking":
        return f"P{pause[1:]}." if pause else "Waiting for you to choose photos."
    if doc.state == "listing":
        listing = f"Reading the list of what you picked ({len(doc.todo):,} so far)"
        return f"{listing} · {pause}" if pause else f"{listing}."
    if doc.state not in ("reading", "done", "expired"):
        return ""
    parts = [f"{doc.done:,} of {doc.total:,} read", _plural(doc.faces, "face", "faces") + " found"]
    if doc.skipped:
        parts.append(f"{doc.skipped:,} could not be read")
    if doc.over:
        parts.append(f"{doc.over:,} more were picked than your limit of {limit:,}")
    if doc.state == "expired":
        parts.append(EXPIRED_WORDS)
    elif pause:
        parts.append(pause)
    return " · ".join(parts)


class ImportStore:
    """`{prefix}photo_imports/{uid}`: one import's progress, in plain fields (ids and counts)."""

    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self._d = docs
        self._col = f"{prefix}photo_imports"

    def _path(self, uid: str) -> str:
        if not owner_ok(uid):
            raise ValueError("bad owner id")
        return f"{self._col}/{uid}"

    async def get(self, uid: str) -> ImportDoc:
        raw = await self._d.get(self._path(uid))
        if not isinstance(raw, dict):
            return ImportDoc()
        state = raw.get("state")
        todo = raw.get("todo")
        people = raw.get("people")
        ids = (
            [t for t in todo if isinstance(t, str) and 0 < len(t) <= ID_MAX]
            if isinstance(todo, list)
            else []
        )
        return ImportDoc(
            session_id=_text(raw.get("session_id"), ID_MAX),
            state=state if state in STATES else "none",
            total=_count(raw.get("total")),
            done=_count(raw.get("done")),
            faces=_count(raw.get("faces")),
            known=_count(raw.get("known")),
            skipped=_count(raw.get("skipped")),
            over=_count(raw.get("over")),
            todo=tuple(ids[:PICKER_MAX]),
            list_token=_text(raw.get("list_token"), TOKEN_MAX),
            cursor=_text(raw.get("cursor"), TOKEN_MAX),
            wrapped=raw.get("wrapped") is True,
            people=tuple(p for p in people if is_person_id(p))[:MAX_PEOPLE]
            if isinstance(people, list)
            else (),
            paused=_text(raw.get("paused"), 16) if raw.get("paused") in PAUSES else "",
        )

    async def put(self, uid: str, doc: ImportDoc) -> None:
        body: dict[str, Any] = {
            "session_id": doc.session_id,
            "state": doc.state,
            "total": doc.total,
            "done": doc.done,
            "faces": doc.faces,
            "known": doc.known,
            "skipped": doc.skipped,
            "over": doc.over,
            "todo": list(doc.todo),
            "list_token": doc.list_token,
            "cursor": doc.cursor,
            "wrapped": doc.wrapped,
            "people": list(doc.people),
            "paused": doc.paused,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        await self._d.write([Set(self._path(uid), body)])

    async def delete(self, uid: str) -> None:
        await self._d.write([Delete(self._path(uid))])


class Importer:
    def __init__(
        self, picker: PickerPort, edge: HomeEdge, faces: RegistryPort, store: ImportStore
    ) -> None:
        self._picker = picker
        self._edge = edge
        self._faces = faces
        self.store = store

    async def _save(self, uid: str, doc: ImportDoc) -> ImportDoc:
        await self.store.put(uid, doc)
        return doc

    async def start(self, uid: str, session_id: str) -> None:
        """A new pick: whatever import was running is replaced."""
        await self.store.put(uid, ImportDoc(session_id, "picking"))

    async def expire(self, uid: str, session_id: str) -> ImportDoc:
        """Google's session is over: keep the counts, drop the ids that can't be read any more."""
        doc = await self.store.get(uid)
        if doc.session_id != session_id:
            doc = ImportDoc(session_id, "picking")
        ended = replace(doc, state="expired", todo=(), list_token="", cursor="", paused="")
        return await self._save(uid, ended)

    async def step(self, uid: str, session_id: str, limits: ImportLimits) -> StepOut:
        doc = await self.store.get(uid)
        if doc.session_id != session_id:
            doc = ImportDoc(session_id, "picking")
        if doc.state in ("done", "expired"):
            return StepOut(doc)
        try:
            kit = await self._edge.ready(uid)
        except EdgeOffline:
            return StepOut(await self._save(uid, replace(doc, paused="laptop")))
        if kit != READY:
            return StepOut(await self._save(uid, replace(doc, paused="kit")))
        try:
            return await self._advance(uid, replace(doc, paused=""), limits)
        except GoogleNotFound:
            return StepOut(await self.expire(uid, session_id))
        except (GoogleAPIError, GoogleNotConnected, PhotosNotGranted):
            latest = await self.store.get(uid)
            if latest.session_id == session_id:
                await self._save(uid, replace(latest, paused="google"))
            raise

    async def _advance(self, uid: str, doc: ImportDoc, limits: ImportLimits) -> StepOut:
        if doc.state == "picking":
            session = await self._picker.get_session(uid, doc.session_id)
            if not session.ready:
                return StepOut(await self._save(uid, doc), picker_uri=session.picker_uri)
            doc = replace(doc, state="listing")
        if doc.state == "listing":
            doc = await self._list(uid, doc, limits)
            if doc.state == "listing":
                return StepOut(doc)
        return await self._read(uid, doc, limits)

    async def _list(self, uid: str, doc: ImportDoc, limits: ImportLimits) -> ImportDoc:
        """Google's list, a page at a time: ids only, at most the owner's limit."""
        for _ in range(MAX_PAGES_PER_STEP):
            items, nxt = await self._picker.list_page(uid, doc.session_id, doc.list_token)
            seen = set(doc.todo)
            fresh = [i.id[:ID_MAX] for i in items if i.id not in seen]
            todo = (*doc.todo, *dict.fromkeys(fresh))
            over = doc.over + max(0, len(todo) - limits.max_picked)
            todo = todo[: limits.max_picked]
            if not nxt:
                listed = replace(
                    doc, state="reading", todo=todo, total=len(todo), over=over, list_token=""
                )
                return await self._save(uid, replace(listed, cursor="", wrapped=False))
            doc = await self._save(uid, replace(doc, todo=todo, over=over, list_token=nxt))
        return doc

    async def _read(self, uid: str, doc: ImportDoc, limits: ImportLimits) -> StepOut:
        registry = await self._faces.state(uid)
        left = list(doc.todo)
        unknown: list[str] = []
        handled = 0
        for _ in range(MAX_PAGES_PER_STEP):
            if handled >= limits.batch or not left:
                break
            items, nxt = await self._picker.list_page(uid, doc.session_id, doc.cursor)
            want = set(left)
            wanted = [i for i in items if i.id in want][: limits.batch - handled]
            if not wanted:
                if nxt:
                    doc = replace(doc, cursor=nxt, wrapped=doc.wrapped or not doc.cursor)
                    continue
                if not doc.cursor or doc.wrapped:
                    # a whole pass from the first page found none of what is left: it is gone
                    doc = replace(doc, skipped=doc.skipped + len(left), cursor="", wrapped=False)
                    left = []
                    break
                doc = replace(doc, cursor="", wrapped=True)
                continue
            for item in wanted:
                try:
                    found = await self._one(uid, item)
                except EdgeOffline:
                    return await self._pause(uid, doc, left, "laptop", unknown)
                except EdgeNotReady:
                    return await self._pause(uid, doc, left, "reader", unknown)
                except EdgeBadReply:
                    return await self._pause(uid, doc, left, "edge", unknown)
                left.remove(item.id)
                handled += 1
                doc = self._count(replace(doc, todo=tuple(left), wrapped=False), found, registry)
                unknown += [h.cluster for h in found or () if not self._named(h, registry)]
                await self.store.put(uid, doc)  # after every photo: a restart loses nothing
            if nxt and not any(i.id in left for i in items):
                doc = replace(doc, cursor=nxt)  # this page is finished
        state = "reading" if left else "done"
        done = replace(doc, todo=tuple(left), state=state)
        return StepOut(await self._save(uid, done), tuple(dict.fromkeys(unknown)))

    async def _pause(
        self, uid: str, doc: ImportDoc, left: list[str], why: str, unknown: list[str]
    ) -> StepOut:
        paused = await self._save(uid, replace(doc, todo=tuple(left), paused=why))
        return StepOut(paused, tuple(dict.fromkeys(unknown)))

    async def _one(self, uid: str, item: PickedItem) -> tuple[FaceHit, ...] | None:
        """One photo to the laptop and dropped. None: it could not be read (skipped)."""
        try:
            image = await self._picker.download(uid, item)
        except PickerError:
            return None
        try:
            (found,) = await self._edge.analyse(uid, [image])
        except EdgeRefused:
            return None  # the laptop could not read this one picture
        finally:
            del image  # dropped before the next one is fetched
        return found

    @staticmethod
    def _named(hit: FaceHit, registry: State) -> bool:
        person = registry.find(hit.person) if hit.person else None
        return person is not None and person.naming and hit.score >= RECOGNITION_THRESHOLD

    def _count(
        self, doc: ImportDoc, found: tuple[FaceHit, ...] | None, registry: State
    ) -> ImportDoc:
        if found is None:
            return replace(doc, skipped=doc.skipped + 1)
        named = [str(h.person) for h in found if self._named(h, registry)]
        people = tuple(dict.fromkeys((*doc.people, *named)))[:MAX_PEOPLE]
        return replace(
            doc,
            done=doc.done + 1,
            faces=doc.faces + len(found),
            known=doc.known + len(named),
            people=people,
        )


__all__ = [
    "PAUSES",
    "ImportDoc",
    "ImportStore",
    "Importer",
    "PickerPort",
    "StepOut",
    "describe",
]
