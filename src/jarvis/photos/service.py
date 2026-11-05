# src/jarvis/photos/service.py
"""Google Photos -> faces and contacts (R4 D8).

begin(uid)    open a Picker session; the owner chooses photos in Google's UI.
collect(uid)  once they have: download ONLY the chosen photos (at most MAX_PICKED), send them to
              the home edge, drop them, close the session. A face is NAMED only when the edge
              matched an `fp_` id that is in the owner's registry, enrolled, consented and scored
              at least RECOGNITION_THRESHOLD (the same rule as `faces.directory`); every other
              face is an unnamed cluster id.
enrol(...)    the owner names an unnamed cluster. The faces registry's consent check runs FIRST
              (`FacesService.add`: a yes from the right person, a guardian for a child); with no
              yes nothing is created and the edge is never told. Nothing enrols by itself.
match_contact suggest the Google Contact with exactly that name (a hint, never an identity).

The cloud keeps ids only: a session id and the unnamed cluster ids, in plain Docs fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from jarvis.contacts.client import Contact, Found
from jarvis.faces.models import Person
from jarvis.faces.ports import RECOGNITION_THRESHOLD
from jarvis.faces.service import FacesService, PersonRejected
from jarvis.integrations.google import GoogleNotFound
from jarvis.logging import get_logger
from jarvis.photos.edge import EdgeOffline, HomeEdge
from jarvis.photos.models import (
    CLUSTER_ID,
    FaceHit,
    ImportResult,
    PickedItem,
    PickerSession,
    RecognisedPerson,
)
from jarvis.photos.picker import PickerError
from jarvis.storage.docs import Docs, Set
from jarvis.undo.store import owner_ok

log = get_logger(__name__)

MAX_CLUSTERS = 200
UNAVAILABLE = "Faces aren't set up on this server, so photos can't be looked at."


class NoSession(RuntimeError):
    """The photos feature can't start (plain words)."""


class PickerPort(Protocol):
    async def create_session(self, uid: str) -> PickerSession: ...
    async def get_session(self, uid: str, session_id: str) -> PickerSession: ...
    async def list_items(self, uid: str, session_id: str) -> tuple[PickedItem, ...]: ...
    async def download(self, uid: str, item: PickedItem) -> bytes: ...
    async def delete_session(self, uid: str, session_id: str) -> None: ...


class ContactsPort(Protocol):
    async def require(self, uid: str) -> None: ...
    async def search(self, uid: str, name: str) -> Found: ...


@dataclass(frozen=True)
class PhotosData:
    session_id: str | None = None
    clusters: tuple[str, ...] = ()


class PhotosState:
    """`{prefix}photos/{uid}` = {session_id, clusters}: ids only, no picture, no name."""

    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self._d = docs
        self._col = f"{prefix}photos"

    def _path(self, uid: str) -> str:
        if not owner_ok(uid):
            raise ValueError("bad owner id")
        return f"{self._col}/{uid}"

    async def get(self, uid: str) -> PhotosData:
        doc = await self._d.get(self._path(uid))
        if not doc:
            return PhotosData()
        sid, raw = doc.get("session_id"), doc.get("clusters")
        clusters = (
            tuple(c for c in raw if isinstance(c, str) and CLUSTER_ID.fullmatch(c))
            if isinstance(raw, list)
            else ()
        )
        return PhotosData(sid if isinstance(sid, str) else None, clusters[:MAX_CLUSTERS])

    async def put(self, uid: str, data: PhotosData) -> None:
        body: dict[str, Any] = {"session_id": data.session_id, "clusters": list(data.clusters)}
        await self._d.write([Set(self._path(uid), body)])


@dataclass(frozen=True)
class Enrolled:
    person: Person
    at_home: bool  # False: the laptop was off; the person is registered and can be finished later
    contact_matched: bool


class PhotosService:
    def __init__(
        self,
        picker: PickerPort,
        edge: HomeEdge,
        faces: FacesService | None,
        contacts: ContactsPort | None,
        state: PhotosState,
    ) -> None:
        self._picker = picker
        self._edge = edge
        self._faces = faces
        self._contacts = contacts
        self._state = state

    async def begin(self, uid: str) -> PickerSession:
        if self._faces is None:
            raise NoSession(UNAVAILABLE)
        session = await self._picker.create_session(uid)
        current = await self._state.get(uid)
        await self._state.put(uid, PhotosData(session.id, current.clusters))
        return session

    async def collect(self, uid: str) -> ImportResult:
        data = await self._state.get(uid)
        if data.session_id is None or self._faces is None:
            return ImportResult("no_session")
        try:
            session = await self._picker.get_session(uid, data.session_id)
        except GoogleNotFound:  # expired or already deleted: start fresh next time
            await self._state.put(uid, PhotosData(None, data.clusters))
            return ImportResult("no_session")
        if not session.ready:
            return ImportResult("waiting")
        items = await self._picker.list_items(uid, data.session_id)
        images, skipped = await self._fetch(uid, items)
        try:
            hits = await self._edge.analyse(uid, images)
        except EdgeOffline:
            return ImportResult("laptop_offline", photos=len(images), skipped=skipped)
        result, clusters = await self._classify(uid, hits, data.clusters)
        await self._picker.delete_session(uid, data.session_id)
        await self._state.put(uid, PhotosData(None, clusters))
        return ImportResult(
            "done",
            photos=len(images),
            faces_found=sum(len(h) for h in hits),
            recognised=result[0],
            unknown_clusters=result[1],
            skipped=skipped,
        )

    async def _fetch(self, uid: str, items: tuple[PickedItem, ...]) -> tuple[list[bytes], int]:
        images: list[bytes] = []
        skipped = 0
        for item in items:
            try:
                images.append(await self._picker.download(uid, item))
            except PickerError:
                skipped += 1
        return images, skipped

    async def _classify(
        self, uid: str, hits: tuple[tuple[FaceHit, ...], ...], known: tuple[str, ...]
    ) -> tuple[tuple[tuple[RecognisedPerson, ...], tuple[str, ...]], tuple[str, ...]]:
        assert self._faces is not None  # noqa: S101 - checked by collect
        registry = await self._faces.state(uid)
        named: dict[str, RecognisedPerson] = {}
        unknown: list[str] = []
        for hit in (h for photo in hits for h in photo):
            person = registry.find(hit.person) if hit.person else None
            if person is not None and person.naming and hit.score >= RECOGNITION_THRESHOLD:
                named[person.id] = RecognisedPerson(person.id, person.name, person.child)
            elif hit.cluster not in unknown:
                unknown.append(hit.cluster)
        merged = tuple(dict.fromkeys((*known, *unknown)))[-MAX_CLUSTERS:]
        return (tuple(named.values()), tuple(unknown)), merged

    async def match_contact(self, uid: str, name: str) -> Contact | None:
        if self._contacts is None:
            return None
        try:
            await self._contacts.require(uid)
            found = await self._contacts.search(uid, name)
        except Exception as exc:  # noqa: BLE001 - a hint only: any trouble means "no match"
            log.warning("contact match skipped", extra={"reason": type(exc).__name__})
            return None
        wanted = name.strip().casefold()
        return next((c for c in found.contacts if c.name.casefold() == wanted), None)

    async def enrol(
        self,
        uid: str,
        cluster: str,
        *,
        name: object,
        relation: object,
        child: bool,
        vip: bool,
        given_by: str,
        consent_version: str,
        confirm: object,
    ) -> Enrolled:
        if self._faces is None:
            raise PersonRejected("unavailable", UNAVAILABLE, status=503)
        data = await self._state.get(uid)
        if cluster not in data.clusters:
            raise PersonRejected("unknown_face", "JARVIS hasn't seen that face.", status=404)
        person = await self._faces.add(  # the consent check lives here and runs first
            uid,
            name=name,
            relation=relation,
            child=child,
            vip=vip,
            given_by=given_by,
            consent_version=consent_version,
            confirm=confirm,
        )
        matched = await self.match_contact(uid, person.name) is not None
        at_home = True
        try:
            await self._edge.enrol(uid, cluster, person.id)
        except EdgeOffline:
            at_home = False
        remaining = tuple(c for c in data.clusters if c != cluster)
        await self._state.put(uid, PhotosData(data.session_id, remaining))
        return Enrolled(person, at_home, matched)


__all__ = ["Enrolled", "NoSession", "PhotosData", "PhotosService", "PhotosState"]
