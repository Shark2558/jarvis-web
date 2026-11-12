# src/jarvis/photos/service.py
"""Google Photos -> faces and contacts (R4 D8; R11.1 O6, O7).

begin(uid)    open a Picker session (up to `photos_max_picked`, 2,000); the owner chooses photos
              in Google's UI. Whatever import was running is replaced.
collect(uid)  ONE step of the import (`photos.imports`): at most `photos_import_batch` of the
              chosen photos, one at a time (download, strip metadata, send to the home edge,
              drop), saved after each, so the helpers' clock, the panel or the chat can drive it
              and a restart or a sleeping laptop resumes where it stopped. One owner runs one
              step at a time, inside a time budget. A face is NAMED only when the edge matched
              an `fp_` id that is in the owner's registry, enrolled, consented and scored at
              least RECOGNITION_THRESHOLD (the same rule as `faces.directory`); every other face
              is an unnamed cluster id (it may become a group worth naming on the laptop).
progress(uid) where the import stands, from the stored counts only (no call to Google or home).
stop(uid)     end the import: the Google session and the ids still to do are dropped.
enrol(...)    the owner names an unnamed cluster or group. The faces registry's consent check
              runs FIRST (`FacesService.add`: a yes from the right person, a guardian for a
              child) and ONCE per person: naming another group as someone already added
              (`enrol_existing`) asks for nothing again. With no yes nothing is created and the
              edge is never told. Nothing enrols by itself. If the laptop is off the person
              stays registered and the cluster stays pending, so a retry only re-sends.
match_contact suggest the Google Contact with exactly that name (a hint, never an identity;
              never for a child).
purge(uid)    erasure: end the Google session, forget every cluster id and the import.

The cloud keeps ids only: a session id, unnamed cluster ids, (cluster, person id) pairs waiting
for the laptop and an import's counts and item ids, in plain Docs fields.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Collection
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol

from jarvis.contacts.client import Contact, Found
from jarvis.faces.models import Person
from jarvis.faces.ports import is_person_id
from jarvis.faces.service import FacesService, PersonRejected
from jarvis.home.ports import HomeUnavailable
from jarvis.logging import get_logger
from jarvis.photos.edge import EdgeNotReady, EdgeOffline, EdgeRefused, HomeEdge
from jarvis.photos.imports import (
    ImportDoc,
    Importer,
    ImportStore,
    PickerPort,
    StepOut,
    describe,
)
from jarvis.photos.models import (
    CLUSTER_ID,
    ImportLimits,
    ImportResult,
    PickerSession,
    RecognisedPerson,
)
from jarvis.storage.docs import Delete, Docs, DocTx, Set
from jarvis.undo.store import owner_ok

log = get_logger(__name__)

MAX_CLUSTERS = 200
COLLECT_BUDGET_S = 25.0  # one step (a panel, a chat tool): every download and laptop call together
STOP_EARLY_S = 1.0  # a step stops starting photos this long before its hard time limit
UNKNOWN_FACE = "JARVIS hasn't seen that face."
UNAVAILABLE = "Faces aren't set up on this server, so photos can't be looked at."
NO_PERSON = "There is no such person. Add them first, with their consent."
# an import's stored pause -> the status a caller sees
PAUSED_STATUS = {
    "laptop": "laptop_offline",
    "kit": "kit_old",
    "reader": "reader_off",
    "edge": "edge_error",
    "google": "reading",
}


class NoSession(RuntimeError):
    """The photos feature can't start (plain words)."""


class ContactsPort(Protocol):
    async def require(self, uid: str) -> None: ...
    async def search(self, uid: str, name: str) -> Found: ...


@dataclass(frozen=True)
class PhotosData:
    session_id: str | None = None
    clusters: tuple[str, ...] = ()
    expires_at: str = ""
    pending: tuple[tuple[str, str], ...] = ()  # (cluster, person_id): registered, not yet at home
    lost: int = 0  # pending names the laptop could not take (its group had gone): told, not dropped


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
    """`{prefix}photos/{uid}` = {session_id, clusters, expires_at, pending, lost}: ids and a
    count only."""

    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self._d = docs
        self.docs, self.prefix = docs, prefix  # the import's progress lives beside this document
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
        lost = doc.get("lost")
        return PhotosData(
            sid if isinstance(sid, str) else None,
            clusters[:MAX_CLUSTERS],
            exp if isinstance(exp, str) else "",
            _pending(doc.get("pending")),
            lost if isinstance(lost, int) and not isinstance(lost, bool) and lost > 0 else 0,
        )

    async def put(self, uid: str, data: PhotosData) -> None:
        body: dict[str, Any] = {
            "session_id": data.session_id,
            "clusters": list(data.clusters),
            "expires_at": data.expires_at,
            "pending": [{"cluster": c, "person": p} for c, p in data.pending],
            "lost": data.lost,
        }
        await self._d.write([Set(self._path(uid), body)])

    async def take_lost(self, uid: str) -> int:
        """How many names were lost since the owner was last told, set back to 0 in the same
        transaction (so it is told once)."""
        path = self._path(uid)

        async def tx(t: DocTx) -> int:
            raw = await t.get(path)
            if not isinstance(raw, dict):
                return 0
            n = raw.get("lost")
            if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
                return 0
            t.set(path, {**raw, "lost": 0})
            return n

        return await self._d.transaction(tx)

    async def delete(self, uid: str) -> None:
        await self._d.write([Delete(self._path(uid))])


@dataclass(frozen=True)
class Enrolled:
    person: Person
    at_home: bool  # False: the laptop was off; the person is registered and can be finished later
    contact_matched: bool


def _without(data: PhotosData, cluster: str) -> PhotosData:
    return replace(
        data,
        clusters=tuple(c for c in data.clusters if c != cluster),
        pending=tuple(p for p in data.pending if p[0] != cluster),
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
        limits: ImportLimits | None = None,
    ) -> None:
        self._picker = picker
        self._edge = edge
        self._faces = faces
        self._contacts = contacts
        self._state = state
        self._now = now
        self._locks: dict[str, asyncio.Lock] = {}
        # `photos_max_picked` and `photos_import_batch`: R11.1's part sets them from the settings
        self.limits = limits or ImportLimits()
        self.imports = ImportStore(state.docs, prefix=state.prefix)
        self._importer = Importer(picker, edge, faces, self.imports) if faces is not None else None

    @property
    def edge(self) -> HomeEdge:
        return self._edge

    def _lock(self, uid: str) -> asyncio.Lock:
        return self._locks.setdefault(uid, asyncio.Lock())

    # ---- the pick and its import ---------------------------------------------------------------

    async def begin(self, uid: str, *, max_items: int | None = None) -> PickerSession:
        if self._faces is None or self._importer is None:
            raise NoSession(UNAVAILABLE)
        async with self._lock(uid):
            current = await self._state.get(uid)
            if current.session_id is not None:  # one live Google session at a time
                await self._picker.delete_session(uid, current.session_id)
            session = await self._picker.create_session(uid, max_items or self.limits.max_picked)
            await self._state.put(
                uid,
                replace(current, session_id=session.id, expires_at=session.expires_at),
            )
            await self._importer.start(uid, session.id)
            return session

    async def collect(self, uid: str, *, budget_s: float | None = None) -> ImportResult:
        """One step of the import. `budget_s`: the helpers' clock gives what it has left."""
        budget = budget_s or COLLECT_BUDGET_S
        async with self._lock(uid):
            before = (await self.imports.get(uid)).done
            try:
                async with asyncio.timeout(budget):
                    return await self._collect(uid, max(0.5, budget - STOP_EARLY_S))
            except TimeoutError:
                log.warning("photo import step ran out of time")
                doc = await self.imports.get(uid)
                status = "reading" if doc.done > before else "timed_out"
                return await self._result(uid, doc, status)

    def _expired(self, data: PhotosData) -> bool:
        try:
            when = datetime.fromisoformat(data.expires_at)
        except ValueError:
            return False  # unknown expiry: Google's own 404 will say so
        return when.tzinfo is not None and when <= self._now()

    async def _collect(self, uid: str, budget_s: float) -> ImportResult:
        data = await self._state.get(uid)
        if data.session_id is None or self._faces is None or self._importer is None:
            return ImportResult("no_session")
        if self._expired(data):
            out = StepOut(await self._importer.expire(uid, data.session_id))
        else:
            out = await self._importer.step(uid, data.session_id, self.limits, budget_s=budget_s)
        doc = out.doc
        clusters = tuple(dict.fromkeys((*data.clusters, *out.unknown)))[-MAX_CLUSTERS:]
        if doc.state == "done":
            await self._picker.delete_session(uid, data.session_id)
            await self._state.put(
                uid, replace(data, session_id=None, clusters=clusters, expires_at="")
            )
        elif doc.state == "expired":
            await self._state.put(
                uid, replace(data, session_id=None, clusters=clusters, expires_at="")
            )
            if doc.done == 0:  # nothing was read: simply start again
                await self.imports.delete(uid)
                return ImportResult("no_session")
        elif clusters != data.clusters:
            await self._state.put(uid, replace(data, clusters=clusters))
        return await self._result(uid, doc, self._status(doc), out)

    @staticmethod
    def _status(doc: ImportDoc) -> str:
        if doc.state in ("done", "expired"):
            return doc.state
        if doc.paused:
            return PAUSED_STATUS.get(doc.paused, "reading")
        return "waiting" if doc.state == "picking" else "reading"

    async def _result(
        self, uid: str, doc: ImportDoc, status: str, out: StepOut | None = None
    ) -> ImportResult:
        named: tuple[RecognisedPerson, ...] = ()
        if doc.people and self._faces is not None:
            registry = await self._faces.state(uid)
            found = (registry.find(p) for p in doc.people)
            named = tuple(
                RecognisedPerson(p.id, p.name, p.child) for p in found if p is not None and p.naming
            )
        return ImportResult(
            status,
            photos=doc.done,
            faces_found=doc.faces,
            recognised=named,
            unknown_clusters=out.unknown if out is not None else (),
            skipped=doc.skipped,
            picker_uri=out.picker_uri if out is not None else "",
            total=doc.total,
            unknown=doc.unknown,
            over=doc.over,
            line=describe(doc, self.limits.max_picked),
        )

    async def progress(self, uid: str) -> ImportResult:
        """Where the import stands, from the stored counts (no call to Google or the laptop)."""
        doc = await self.imports.get(uid)
        if doc.state == "none":
            return ImportResult("no_session")
        return await self._result(uid, doc, self._status(doc))

    async def stop(self, uid: str) -> None:
        """End the import: Google's session and the ids still to do are dropped."""
        async with self._lock(uid):
            data = await self._state.get(uid)
            try:
                if data.session_id is not None:
                    await self._picker.delete_session(uid, data.session_id)
            finally:
                await self._state.put(uid, replace(data, session_id=None, expires_at=""))
                await self.imports.delete(uid)

    # ---- contacts and erasure ------------------------------------------------------------------

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
        """Erasure hook (privacy panel): end the Google session, forget every cluster id and
        the import's progress."""
        async with self._lock(uid):
            data = await self._state.get(uid)
            try:
                if data.session_id is not None:
                    await self._picker.delete_session(uid, data.session_id)
            finally:  # the state goes even when Google cannot be reached (I2 F3)
                await self._state.delete(uid)
                await self.imports.delete(uid)

    # ---- naming: consent first, once per person ------------------------------------------------

    async def pending(self, uid: str) -> tuple[tuple[str, str], ...]:
        """(cluster, person id) pairs registered here and still waiting for the laptop."""
        return (await self._state.get(uid)).pending

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
        known: Collection[str] = (),
    ) -> Enrolled:
        """`known`: group ids the laptop itself listed (R11.1: a group from the watched folder
        never passed through an import here)."""
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
            elif cluster in data.clusters or cluster in known:
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
                data = await self._wait(uid, data, cluster, person.id)
            else:
                raise PersonRejected("unknown_face", UNKNOWN_FACE, status=404)
            return await self._finish(uid, data, cluster, person)

    async def enrol_existing(
        self, uid: str, cluster: str, person_id: str, *, known: Collection[str] = ()
    ) -> Enrolled:
        """Another group of someone ALREADY added: their consent is on record, so nothing is
        asked again (the consent check ran once, when they were added)."""
        if self._faces is None:
            raise PersonRejected("unavailable", UNAVAILABLE, status=503)
        async with self._lock(uid):
            data = await self._state.get(uid)
            person = (
                (await self._faces.state(uid)).find(person_id) if is_person_id(person_id) else None
            )
            if person is None or person.state == "deleting" or not person.consent_at:
                raise PersonRejected("not_found", NO_PERSON, status=404)
            waiting = dict(data.pending)
            if waiting.get(cluster, person.id) != person.id:
                raise PersonRejected("unknown_face", UNKNOWN_FACE, status=404)
            if cluster not in waiting:
                if cluster not in data.clusters and cluster not in known:
                    raise PersonRejected("unknown_face", UNKNOWN_FACE, status=404)
                data = await self._wait(uid, data, cluster, person.id)
            return await self._finish(uid, data, cluster, person)

    async def _wait(self, uid: str, data: PhotosData, cluster: str, person_id: str) -> PhotosData:
        if not CLUSTER_ID.fullmatch(cluster):
            raise PersonRejected("unknown_face", UNKNOWN_FACE, status=404)
        pending = (*data.pending, (cluster, person_id))[-MAX_CLUSTERS:]
        new = replace(data, pending=pending)
        await self._state.put(uid, new)
        return new

    async def _finish(self, uid: str, data: PhotosData, cluster: str, person: Person) -> Enrolled:
        at_home = await self._send_to_home(uid, cluster, person.id)
        if at_home is None:
            await self._state.put(uid, _without(data, cluster))
            raise PersonRejected("unknown_face", UNKNOWN_FACE, status=404)
        if at_home:
            await self._state.put(uid, _without(data, cluster))
        matched = not person.child and await self.match_contact(uid, person.name) is not None
        return Enrolled(person, at_home, matched)

    async def _send_to_home(self, uid: str, cluster: str, person_id: str) -> bool | None:
        """True: the laptop named the group. False: it will be told later (off, asleep, or its
        consent list not yet up to date). None: the laptop no longer has that group."""
        if self._faces is None:
            return False
        try:
            pictures = await self._edge.enrol(uid, cluster, person_id)
        except (EdgeOffline, EdgeNotReady, HomeUnavailable):
            return False
        except EdgeRefused as exc:
            if exc.code == "no_consent":
                return False  # the laptop hears of the consent with its next check-in
            log.warning("the laptop refused a group's name", extra={"reason": exc.code})
            return None
        if pictures > 0:  # recognised from now on, without waiting for the next heartbeat
            await self._faces.apply_pictures(uid, {person_id: pictures})
        return True

    async def retry_pending(self, uid: str) -> int:
        """Names registered while the laptop was away: tell it now. Returns how many it took."""
        if self._faces is None:
            return 0
        done = 0
        async with self._lock(uid):
            data = await self._state.get(uid)
            if not data.pending:
                return 0
            await self._faces.push(uid)  # the laptop must know of the consent before the name
            registry = await self._faces.state(uid)
            for cluster, person_id in data.pending:
                person = registry.find(person_id)
                if person is None or person.state == "deleting":
                    data = _without(data, cluster)
                    await self._state.put(uid, data)
                    continue
                sent = await self._send_to_home(uid, cluster, person_id)
                if sent is False:
                    break  # still away: the rest wait too
                data = _without(data, cluster)
                if sent is None:  # the group had gone from the laptop (review C-code M7)
                    data = replace(data, lost=data.lost + 1)  # the owner is told, never silence
                await self._state.put(uid, data)
                done += 1 if sent else 0
        return done

    async def names_lost(self, uid: str) -> int:
        """Names the laptop could not take since the owner was last told (a count)."""
        return (await self._state.get(uid)).lost

    async def take_lost(self, uid: str) -> int:
        """The count of lost names, set back to 0: the caller tells the owner."""
        async with self._lock(uid):
            return await self._state.take_lost(uid)


__all__ = ["Enrolled", "NoSession", "PhotosData", "PhotosService", "PhotosState"]
