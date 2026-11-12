# src/jarvis/photos/imports.py
"""A Google Photos import as a background, resumable job (R11.1 O6; plan D14).

The import's document and who may step it: `photos.import_store` (ids and counts only; a step
claims the import in a transaction first, so two instances never step it together: review
C-code H2). `Importer.step` does ONE step and saves after every photo, so a restart, a sleeping
laptop or a step that runs out of time loses nothing:

1. the laptop first (one cheap call): asleep, or on a kit from before the photo routes, means
   nothing is downloaded for it and the import says why it is paused;
2. picking -> listing: Google's list is read a page at a time and only the item ids are kept
   (at most the owner's `photos_max_picked`; what was picked beyond it is counted, not imported);
3. reading: photos one at a time (download, metadata stripped by the Picker client, sent to the
   laptop, dropped), as many as the step's time allows (review C-code M6): at least the owner's
   `photos_import_batch` when they fit, at most `STEP_MAX_PHOTOS`, and never one the step does
   not expect to finish before its time is up (the slowest photo so far is the measure).
   Google's download links expire, so each step asks for the page again and no link is ever
   kept; `cursor` remembers which page holds the next photo. Photos that are no longer in the
   pick are counted as "could not be read" after one whole pass of the list finds none of them;
4. a photo Google fails to hand over for a moment (5xx, 429, a timeout: `PickerRetry`) is tried
   again in the step with a short backoff; if it still fails it stays to do, the import pauses
   ("Google Photos isn't answering") and the next step tries it again; only after
   `MAX_STUCK_STEPS` steps in a row is it counted as "could not be read" (review C-code M1);
5. a session Google has ended (404) stops the import cleanly: "pick again to continue", with
   what was done kept and the ids still to do dropped.
"""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Protocol

from jarvis.faces.models import State
from jarvis.faces.ports import RECOGNITION_THRESHOLD
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
from jarvis.photos.errors import PickerError, PickerRetry
from jarvis.photos.import_store import (
    ID_MAX,
    PAUSES,
    ImportDoc,
    ImportStore,
    LeaseLost,
    describe,
    pace,
)
from jarvis.photos.models import FaceHit, ImportLimits, PickedItem, PickerSession
from jarvis.photos.picker import PhotosNotGranted

log = get_logger(__name__)

MAX_PAGES_PER_STEP = 30
MAX_PEOPLE = 30
STEP_MAX_PHOTOS = 50  # `photos_import_batch`'s own ceiling: a step never reads more
RETRY_WAITS_S = (1.0, 3.0)  # a photo Google failed to hand over: tried again after these
MAX_STUCK_STEPS = 5
LEASE_MARGIN_S = 30.0


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
class StepOut:
    doc: ImportDoc
    unknown: tuple[str, ...] = ()  # unnamed cluster ids seen in this step
    picker_uri: str = ""  # still picking: Google's link again
    busy: bool = False  # another step (another instance) holds the import right now


class _Still(Exception):
    """Google still would not hand this photo over after the in-step retries."""


@dataclass
class _Step:
    """One step's claim and clock."""

    holder: str
    lease_s: float
    deadline: float | None
    started: float
    slowest: float = 0.0
    read: int = 0


class Importer:
    def __init__(
        self,
        picker: PickerPort,
        edge: HomeEdge,
        faces: RegistryPort,
        store: ImportStore,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._picker = picker
        self._edge = edge
        self._faces = faces
        self.store = store
        self._clock = clock
        self._sleep = sleep

    async def _save(self, uid: str, doc: ImportDoc, st: _Step) -> ImportDoc:
        await self.store.put(uid, doc, st.holder, st.lease_s)
        return doc

    async def start(self, uid: str, session_id: str) -> None:
        """A new pick: whatever import was running is replaced."""
        await self.store.start(uid, ImportDoc(session_id, "picking"))

    async def expire(self, uid: str, session_id: str, holder: str = "") -> ImportDoc:
        """Google's session is over (a finished import stays finished)."""
        return await self.store.expire(uid, session_id, holder)

    async def step(
        self, uid: str, session_id: str, limits: ImportLimits, *, budget_s: float = 25.0
    ) -> StepOut:
        """One step inside `budget_s`. Does nothing while another step holds the import."""
        now = self._clock()
        st = _Step(secrets.token_hex(8), budget_s + LEASE_MARGIN_S, now + budget_s, now)
        doc = await self.store.claim(uid, session_id, st.holder, st.lease_s)
        if doc is None:
            return StepOut(await self.store.get(uid), busy=True)
        try:
            return await self._step(uid, doc, limits, st)
        except LeaseLost:
            log.info("an import step stopped: another step or a new pick took over")
            return StepOut(await self.store.get(uid), busy=True)
        finally:
            await self.store.release(uid, st.holder)

    async def _step(self, uid: str, doc: ImportDoc, limits: ImportLimits, st: _Step) -> StepOut:
        if doc.state in ("done", "expired"):
            return StepOut(doc)
        try:
            kit = await self._edge.ready(uid)
        except EdgeOffline:
            return StepOut(await self._save(uid, replace(doc, paused="laptop"), st))
        if kit != READY:
            return StepOut(await self._save(uid, replace(doc, paused="kit"), st))
        try:
            return await self._advance(uid, replace(doc, paused=""), limits, st)
        except GoogleNotFound:
            return StepOut(await self.expire(uid, doc.session_id, st.holder))
        except (GoogleAPIError, GoogleNotConnected, PhotosNotGranted):
            latest = await self.store.get(uid)
            if latest.session_id == doc.session_id:
                await self._save(uid, replace(latest, paused="google"), st)
            raise

    async def _advance(self, uid: str, doc: ImportDoc, limits: ImportLimits, st: _Step) -> StepOut:
        if doc.state == "picking":
            session = await self._picker.get_session(uid, doc.session_id)
            if not session.ready:
                return StepOut(await self._save(uid, doc, st), picker_uri=session.picker_uri)
            doc = replace(doc, state="listing")
        if doc.state == "listing":
            doc = await self._list(uid, doc, limits, st)
            if doc.state == "listing":
                return StepOut(doc)
        return await self._read(uid, doc, limits, st)

    async def _list(self, uid: str, doc: ImportDoc, limits: ImportLimits, st: _Step) -> ImportDoc:
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
                return await self._save(uid, replace(listed, cursor="", wrapped=False), st)
            doc = await self._save(uid, replace(doc, todo=todo, over=over, list_token=nxt), st)
        return doc

    def _room(self, st: _Step, limits: ImportLimits) -> bool:
        """Whether this step reads another photo: up to STEP_MAX_PHOTOS, and only one it
        expects to finish before its time is up (the first photo of a step always starts)."""
        if st.read >= min(max(limits.batch, limits.most), STEP_MAX_PHOTOS):
            return False
        if st.read == 0 or st.deadline is None:
            return True
        return self._clock() + max(st.slowest, 0.0) <= st.deadline

    async def _read(self, uid: str, doc: ImportDoc, limits: ImportLimits, st: _Step) -> StepOut:
        registry = await self._faces.state(uid)
        left = list(doc.todo)
        unknown: list[str] = []
        for _ in range(MAX_PAGES_PER_STEP):
            if not left or not self._room(st, limits):
                break
            items, nxt = await self._picker.list_page(uid, doc.session_id, doc.cursor)
            want = set(left)
            wanted = [i for i in items if i.id in want]
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
                if not self._room(st, limits):
                    break
                began = self._clock()
                try:
                    found = await self._one(uid, item)
                except EdgeOffline:
                    return await self._pause(uid, doc, left, "laptop", unknown, st)
                except EdgeNotReady:
                    return await self._pause(uid, doc, left, "reader", unknown, st)
                except EdgeBadReply:
                    return await self._pause(uid, doc, left, "edge", unknown, st)
                except _Still:
                    doc, left, gave_up = self._stuck(doc, left, item.id)
                    if not gave_up:
                        return await self._pause(uid, doc, left, "google", unknown, st)
                    doc = await self._save(uid, doc, st)
                    continue
                st.read += 1
                st.slowest = max(st.slowest, self._clock() - began)
                left.remove(item.id)
                fresh = replace(doc, todo=tuple(left), wrapped=False, stuck="", stuck_tries=0)
                doc = self._count(fresh, found, registry)
                unknown += [h.cluster for h in found or () if not self._named(h, registry)]
                doc = await self._save(uid, self._paced(doc, st), st)  # a restart loses nothing
            if nxt and not any(i.id in left for i in items):
                doc = replace(doc, cursor=nxt)  # this page is finished
        state = "reading" if left else "done"
        done = replace(doc, todo=tuple(left), state=state)
        return StepOut(await self._save(uid, done, st), tuple(dict.fromkeys(unknown)))

    def _paced(self, doc: ImportDoc, st: _Step) -> ImportDoc:
        took = self._clock() - st.started
        return replace(doc, rate_mpps=int(st.read * 1000 / took)) if took > 0 else doc

    @staticmethod
    def _stuck(doc: ImportDoc, left: list[str], item: str) -> tuple[ImportDoc, list[str], bool]:
        """A photo Google would not hand over. Kept to do (and the step pauses) until it has
        failed in MAX_STUCK_STEPS steps in a row; then it is counted as could not be read."""
        tries = doc.stuck_tries + 1 if doc.stuck == item else 1
        if tries < MAX_STUCK_STEPS:
            return replace(doc, stuck=item, stuck_tries=tries), left, False
        rest = [i for i in left if i != item]
        gone = replace(doc, todo=tuple(rest), skipped=doc.skipped + 1, stuck="", stuck_tries=0)
        return gone, rest, True

    async def _pause(
        self,
        uid: str,
        doc: ImportDoc,
        left: list[str],
        why: str,
        unknown: list[str],
        st: _Step,
    ) -> StepOut:
        paused = await self._save(uid, replace(doc, todo=tuple(left), paused=why), st)
        return StepOut(paused, tuple(dict.fromkeys(unknown)))

    async def _download(self, uid: str, item: PickedItem) -> bytes | None:
        """The photo, or None when it is bad for good (not a JPEG, too large, 403/404).
        A passing failure is tried again with a short backoff, then raised as `_Still`."""
        for wait in (*RETRY_WAITS_S, None):
            try:
                return await self._picker.download(uid, item)
            except PickerRetry:
                if wait is None:
                    raise _Still() from None
                await self._sleep(wait)
            except PickerError:
                return None
        raise _Still()

    async def _one(self, uid: str, item: PickedItem) -> tuple[FaceHit, ...] | None:
        """One photo to the laptop and dropped. None: it could not be read (skipped)."""
        image = await self._download(uid, item)
        if image is None:
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
    "STEP_MAX_PHOTOS",
    "ImportDoc",
    "ImportStore",
    "Importer",
    "LeaseLost",
    "PickerPort",
    "StepOut",
    "describe",
    "pace",
]
