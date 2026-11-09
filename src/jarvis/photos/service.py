# src/jarvis/photos/service.py
"""Google Photos -> faces and contacts (R4 D8).

begin(uid)    open a Picker session; the owner chooses photos in Google's UI.
collect(uid)  once they have: take ONLY the chosen photos (at most MAX_PICKED) one at a time
              (download, strip metadata, send to the home edge, drop), then close the session.
              One owner runs one begin/collect/enrol at a time and collect has a time budget.
              A face is NAMED only when the edge matched an `fp_` id that is in the owner's
              registry, enrolled, consented and scored at least RECOGNITION_THRESHOLD (the same
              rule as `faces.directory`); every other face is an unnamed cluster id.
enrol(...)    the owner names an unnamed cluster. The faces registry's consent check runs FIRST
              (`FacesService.add`: a yes from the right person, a guardian for a child); with no
              yes nothing is created and the edge is never told. Nothing enrols by itself. If the
              laptop is off the person stays registered and the cluster stays pending, so a retry
              only re-sends to the edge.
match_contact suggest the Google Contact with exactly that name (a hint, never an identity;
              never for a child).
purge(uid)    erasure: end the Google session and forget every cluster id.

The cloud keeps ids only: a session id, the unnamed cluster ids and (cluster, person id) pairs
waiting for the laptop, in plain Docs fields.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from jarvis.contacts.client import Contact, Found
from jarvis.faces.models import Person
from jarvis.faces.ports import RECOGNITION_THRESHOLD, is_person_id
from jarvis.faces.service import FacesService, PersonRejected
from jarvis.home.ports import HomeUnavailable
from jarvis.integrations.google import GoogleNotFound
from jarvis.logging import get_logger
from jarvis.photos.edge import EdgeBadReply, EdgeOffline, HomeEdge
from jarvis.photos.errors import PickerError
from jarvis.photos.models import (
    CLUSTER_ID,
    FaceHit,
    ImportResult,
    PickedItem,
    PickerSession,
    RecognisedPerson,
)
from jarvis.storage.docs import Delete, Docs, Set
from jarvis.undo.store import owner_ok

log = get_logger(__name__)

MAX_CLUSTERS = 200
COLLECT_BUDGET_S = 120.0  # one import: every download and home-edge call together
UNKNOWN_FACE = "JARVIS hasn't seen that face."
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
    expires_at: str = ""
    pending: tuple[tuple[str, str], ...] = ()  # (cluster, person_id): registered, not yet at home


def _pending(raw: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(raw, list):
        return ()
    out: list[tuple[str, str]] = []
    for row in raw[:MAX_CLUSTERS]:
        cluster = row.get("cluster") if isinstance(row, dict) else None
        person = row.get("person") if isinstance(row, dict) else None
        if isinstance(cluster, str) and CLUSTER_ID.fullmatch(cluster) and is_person_id(person):
            out.append((cluster, str(person)))
    return tuple(out)


class PhotosState:
    """`{prefix}photos/{uid}` = {session_id, clusters, expires_at, pending}: ids only."""

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
        sid, raw, exp = doc.get("session_id"), doc.get("clusters"), doc.get("expires_at")
        clusters = (
            tuple(c for c in raw if isinstance(c, str) and CLUSTER_ID.fullmatch(c))
            if isinstance(raw, list)
            else ()
        )
        return PhotosData(
            sid if isinstance(sid, str) else None,
            clusters[:MAX_CLUSTERS],
            exp if isinstance(exp, str) else "",
            _pending(doc.get("pending")),
        )

    async def put(self, uid: str, data: PhotosData) -> None:
        body: dict[str, Any] = {
            "session_id": data.session_id,
            "clusters": list(data.clusters),
            "expires_at": data.expires_at,
            "pending": [{"cluster": c, "person": p} for c, p in data.pending],
        }
        await self._d.write([Set(self._path(uid), body)])

    async def delete(self, uid: str) -> None:
        await self._d.write([Delete(self._path(uid))])


@dataclass(frozen=True)
class Enrolled:
    person: Person
    at_home: bool  # False: the laptop was off; the person is registered and can be finished later
    contact_matched: bool


def _without(data: PhotosData, cluster: str) -> PhotosData:
    return PhotosData(
        data.session_id,
        tuple(c for c in data.clusters if c != cluster),
        data.expires_at,
        tuple(p for p in data.pending if p[0] != cluster),
    )


class PhotosService:
    def __init__(
        self,
        picker: PickerPort,
        edge: HomeEdge,
        faces: FacesService | None,
        contacts: ContactsPort | None,
        state: PhotosState,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._picker = picker
        self._edge = edge
        self._faces = faces
        self._contacts = contacts
        self._state = state
        self._now = now
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, uid: str) -> asyncio.Lock:
        return self._locks.setdefault(uid, asyncio.Lock())

    async def begin(self, uid: str) -> PickerSession:
        if self._faces is None:
            raise NoSession(UNAVAILABLE)
        async with self._lock(uid):
            current = await self._state.get(uid)
            if current.session_id is not None:  # one live Google session at a time
                await self._picker.delete_session(uid, current.session_id)
            session = await self._picker.create_session(uid)
            await self._state.put(
                uid,
                PhotosData(session.id, current.clusters, session.expires_at, current.pending),
            )
            return session

    async def collect(self, uid: str) -> ImportResult:
        async with self._lock(uid):
            try:
                async with asyncio.timeout(COLLECT_BUDGET_S):
                    return await self._collect(uid)
            except TimeoutError:
                log.warning("photo import ran out of time")
                return ImportResult("timed_out")

    def _expired(self, data: PhotosData) -> bool:
        try:
            when = datetime.fromisoformat(data.expires_at)
        except ValueError:
            return False  # unknown expiry: Google's own 404 will say so
        return when.tzinfo is not None and when <= self._now()

    async def _forget(self, uid: str, data: PhotosData) -> ImportResult:
        await self._state.put(uid, PhotosData(None, data.clusters, "", data.pending))
        return ImportResult("no_session")

    async def _collect(self, uid: str) -> ImportResult:
        data = await self._state.get(uid)
        if data.session_id is None or self._faces is None:
            return ImportResult("no_session")
        if self._expired(data):
            return await self._forget(uid, data)
        try:
            session = await self._picker.get_session(uid, data.session_id)
            if not session.ready:
                return ImportResult("waiting", picker_uri=session.picker_uri)
            items = await self._picker.list_items(uid, data.session_id)
        except GoogleNotFound:  # expired or already deleted: start fresh next time
            return await self._forget(uid, data)
        return await self._import(uid, data, items)

    async def _import(
        self, uid: str, data: PhotosData, items: tuple[PickedItem, ...]
    ) -> ImportResult:
        hits: list[tuple[FaceHit, ...]] = []
        skipped = 0
        for item in items:
            try:
                image = await self._picker.download(uid, item)
            except PickerError:
                skipped += 1
                continue
            try:
                (found,) = await self._edge.analyse(uid, [image])
            except EdgeOffline:
                return ImportResult("laptop_offline", photos=len(hits), skipped=skipped)
            except EdgeBadReply:
                return ImportResult("edge_error", photos=len(hits), skipped=skipped)
            finally:
                del image  # dropped before the next one is fetched
            hits.append(found)
        named, unknown, clusters = await self._classify(uid, tuple(hits), data.clusters)
        if data.session_id is not None:
            await self._picker.delete_session(uid, data.session_id)
        await self._state.put(uid, PhotosData(None, clusters, "", data.pending))
        return ImportResult(
            "done",
            photos=len(hits),
            faces_found=sum(len(h) for h in hits),
            recognised=named,
            unknown_clusters=unknown,
            skipped=skipped,
        )

    async def _classify(
        self, uid: str, hits: tuple[tuple[FaceHit, ...], ...], known: tuple[str, ...]
    ) -> tuple[tuple[RecognisedPerson, ...], tuple[str, ...], tuple[str, ...]]:
        if self._faces is None:
            raise NoSession(UNAVAILABLE)
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
        return tuple(named.values()), tuple(unknown), merged

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

    async def purge(self, uid: str) -> None:
        """Erasure hook (privacy panel): end the Google session, forget every cluster id."""
        async with self._lock(uid):
            data = await self._state.get(uid)
            try:
                if data.session_id is not None:
                    await self._picker.delete_session(uid, data.session_id)
            finally:  # the state goes even when Google cannot be reached (I2 F3)
                await self._state.delete(uid)

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
        async with self._lock(uid):
            data = await self._state.get(uid)
            waiting = dict(data.pending)
            if cluster in waiting:  # registered earlier while the laptop was off: only re-send
                person = (await self._faces.state(uid)).find(waiting[cluster])
                if person is None or person.state == "deleting":
                    await self._state.put(uid, _without(data, cluster))
                    raise PersonRejected("unknown_face", UNKNOWN_FACE, status=404)
            elif cluster in data.clusters:
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
                data = PhotosData(
                    data.session_id,
                    data.clusters,
                    data.expires_at,
                    (*data.pending, (cluster, person.id)),
                )
                await self._state.put(uid, data)
            else:
                raise PersonRejected("unknown_face", UNKNOWN_FACE, status=404)
            at_home = await self._send_to_home(uid, cluster, person.id)
            if at_home:
                await self._state.put(uid, _without(data, cluster))
            matched = not person.child and await self.match_contact(uid, person.name) is not None
            return Enrolled(person, at_home, matched)

    async def _send_to_home(self, uid: str, cluster: str, person_id: str) -> bool:
        try:
            await self._edge.enrol(uid, cluster, person_id)
        except (EdgeOffline, HomeUnavailable):
            return False
        return True


__all__ = ["Enrolled", "NoSession", "PhotosData", "PhotosService", "PhotosState"]
