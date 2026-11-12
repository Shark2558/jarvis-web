# src/jarvis/facegroups/service.py
"""Face groups in the cloud (R11.1 O7; plan D15, D21-C): the owner's view of the groups his home
laptop found, naming one, and forgetting them. Layer 5 over the photos service and the home edge.

view        the unnamed groups worth naming, as ids and counts. The laptop is asked; when it is
            asleep the last answer is shown and marked as such. To see WHO a group is, the owner
            opens the laptop's own page: no crop ever comes here.
name        a group becomes a person. The Faces registry's consent check runs first and once per
            person (`PhotosService.enrol` -> `FacesService.add`: a yes from the person, a
            guardian's for a child); without it nothing is created and the laptop is never told.
            Naming another group as someone already added asks for nothing again.
forget      one group, or all unnamed groups and stray faces. It is DONE only when the laptop
            answers with its own counts; while the laptop is away the ask waits here and the
            5-minute poll retries it.
poll        (the helpers' clock) retry what waits, refresh the copy, and say once, with a count
            only, when new groups are worth naming (alert kind `faces_to_name`).
Nothing here is logged or audited beyond counts.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from jarvis.core.guardrails import ActionRisk
from jarvis.facegroups.store import GroupsDoc, GroupsStore
from jarvis.faces.service import PersonRejected
from jarvis.logging import get_logger
from jarvis.notify.ports import Notifier, Signal
from jarvis.photos.edge import EdgeBadReply, EdgeNotReady, EdgeOffline, EdgeRefused
from jarvis.photos.models import CLUSTER_ID, GroupAtHome
from jarvis.photos.service import Enrolled, PhotosService

log = get_logger(__name__)

AUDIT_AGENT = "faces"
OFF = (
    "Photos and face groups are off on this server: they need Google sign-in, Faces and the "
    "home kit."
)
NO_GROUP = "JARVIS doesn't know that group. Open the Faces panel again to see the current list."
ALERT_ONE = "1 new group of faces to name, Sir. Open Faces -> Unnamed groups."
ALERT_MANY = "{n} new groups of faces to name, Sir. Open Faces -> Unnamed groups."
_AWAY = (EdgeOffline, EdgeBadReply, EdgeNotReady, EdgeRefused)


@dataclass(frozen=True)
class GroupsView:
    available: bool
    laptop: str = "off"  # online | offline | off (the part is off on this server)
    heard_at: str = ""
    groups: tuple[GroupAtHome, ...] = ()
    strays: int = 0
    named: int = 0
    engine_ready: bool = False
    folder: str = "off"
    read: int = 0
    keep_days: int = 90
    names_waiting: int = 0  # named here, the laptop not told yet
    forgets_waiting: int = 0  # asked to forget, the laptop not yet confirmed
    reason: str = ""


@dataclass(frozen=True)
class Forgotten:
    done: bool  # the laptop confirmed it
    forgotten: int = 0
    left: int = 0  # unnamed groups and stray faces still on the laptop, as it said


class FaceGroupsService:
    def __init__(
        self,
        photos: Callable[[], PhotosService | None],
        store: GroupsStore,
        *,
        notifier: Callable[[], Notifier | None] | None = None,
        audit: Any = None,
        laptop_online: Callable[[], Callable[[str], Awaitable[bool]] | None] | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._photos = photos
        self.store = store
        self._notifier = notifier
        self._audit = audit
        self._laptop_online = laptop_online
        self._now = now

    # ---- the view ------------------------------------------------------------------------------

    async def _refresh(self, uid: str, photos: PhotosService, doc: GroupsDoc) -> GroupsDoc:
        """Ask the laptop and keep its answer. Raises the edge's own error when it can't."""
        home = await photos.edge.groups(uid)
        live = {g.id for g in home.groups}
        fresh = replace(
            doc,
            home=home,
            heard_at=self._now().isoformat(),
            told=tuple(t for t in doc.told if t in live),
        )
        await self.store.put(uid, fresh)
        return fresh

    async def view(self, uid: str, *, ask: bool = True) -> GroupsView:
        photos = self._photos()
        if photos is None:
            return GroupsView(False, reason=OFF)
        doc = await self.store.get(uid)
        laptop = "offline"
        if ask:
            try:
                doc = await self._refresh(uid, photos, doc)
                laptop = "online"
            except _AWAY as exc:
                log.info(
                    "face groups: the laptop did not answer", extra={"why": type(exc).__name__}
                )
        h = doc.home
        named = {cluster for cluster, _ in await photos.pending(uid)}  # people now, not groups
        unnamed = [g for g in h.groups if g.id not in named]
        return GroupsView(
            True,
            laptop,
            doc.heard_at,
            tuple(g for g in doc.shown if g.id not in named),
            0 if doc.forget_all else h.strays,
            h.named,
            h.engine_ready,
            h.folder,
            h.read,
            h.keep_days,
            len(named),
            (len(unnamed) + h.strays if doc.forget_all else len(doc.forget)),
        )

    async def _known(self, uid: str, photos: PhotosService, group: str) -> tuple[str, ...]:
        """The group ids the laptop listed (asked now; its last answer if it is asleep)."""
        if not isinstance(group, str) or not CLUSTER_ID.fullmatch(group):
            raise PersonRejected("unknown_face", NO_GROUP, status=404)
        doc = await self.store.get(uid)
        try:
            doc = await self._refresh(uid, photos, doc)
        except _AWAY:
            pass
        ids = tuple(g.id for g in doc.shown)
        if group not in ids:
            raise PersonRejected("unknown_face", NO_GROUP, status=404)
        return ids

    # ---- naming --------------------------------------------------------------------------------

    def _need(self) -> PhotosService:
        photos = self._photos()
        if photos is None:
            raise PersonRejected("unavailable", OFF, status=503)
        return photos

    async def name(self, uid: str, group: str, **consent: Any) -> Enrolled:
        """A new person for this group: the consent statement decides (`FacesService.add`)."""
        photos = self._need()
        known = await self._known(uid, photos, group)
        done = await photos.enrol(uid, group, known=known, **consent)
        await self._after_naming(uid, done)
        return done

    async def name_existing(self, uid: str, group: str, person_id: str) -> Enrolled:
        """This group is someone already added with their consent: nothing is asked again."""
        photos = self._need()
        known = await self._known(uid, photos, group)
        done = await photos.enrol_existing(uid, group, person_id, known=known)
        await self._after_naming(uid, done)
        return done

    async def _after_naming(self, uid: str, done: Enrolled) -> None:
        await self._record(uid, "faces_group_name", 1, "at home" if done.at_home else "waiting")
        if done.at_home:  # the laptop's list changed: keep the copy in step (best effort)
            photos = self._photos()
            if photos is not None:
                try:
                    await self._refresh(uid, photos, await self.store.get(uid))
                except _AWAY:
                    pass

    # ---- forgetting: done only when the laptop says so -----------------------------------------

    async def _names_wait(self, uid: str, photos: PhotosService) -> bool:
        """A group named while the laptop slept is a person, not an unnamed group: the laptop
        hears the name BEFORE any forget. True while a name still could not be delivered."""
        if not await photos.pending(uid):
            return False
        await photos.retry_pending(uid)
        return bool(await photos.pending(uid))

    async def forget(self, uid: str, group: str) -> Forgotten:
        photos = self._need()
        if not isinstance(group, str) or not CLUSTER_ID.fullmatch(group):
            raise PersonRejected("unknown_face", NO_GROUP, status=404)
        if group in {cluster for cluster, _ in await photos.pending(uid)}:
            raise PersonRejected("unknown_face", NO_GROUP, status=404)  # named: in Faces now
        return await self._forget_one(uid, photos, group)

    async def _forget_one(self, uid: str, photos: PhotosService, group: str) -> Forgotten:
        doc = await self.store.get(uid)
        try:
            said = await photos.edge.forget(uid, [group])
        except _AWAY:
            waiting = tuple(dict.fromkeys((*doc.forget, group)))
            await self.store.put(uid, replace(doc, forget=waiting))
            return Forgotten(False)
        kept = tuple(g for g in doc.home.groups if g.id != group)
        cleared = tuple(f for f in doc.forget if f != group)
        await self.store.put(uid, replace(doc, home=replace(doc.home, groups=kept), forget=cleared))
        await self._record(uid, "faces_group_forget", said.forgotten, "confirmed by the laptop")
        return Forgotten(True, said.forgotten, said.left)

    async def forget_all(self, uid: str) -> Forgotten:
        photos = self._need()
        names_wait = await self._names_wait(uid, photos)
        doc = await self.store.get(uid)
        try:
            if names_wait:
                raise EdgeOffline("a name still waits for the laptop")
            said = await photos.edge.forget(uid, None)
        except _AWAY:
            await self.store.put(uid, replace(doc, forget_all=True))
            return Forgotten(False, left=doc.kept)
        home = replace(doc.home, groups=(), more=0, strays=said.left)
        await self.store.put(uid, replace(doc, home=home, told=(), forget=(), forget_all=False))
        await self._record(
            uid, "faces_group_forget", said.forgotten, "all; confirmed by the laptop"
        )
        return Forgotten(True, said.forgotten, said.left)

    # ---- the clock -----------------------------------------------------------------------------

    async def _online(self, uid: str) -> bool:
        probe = self._laptop_online() if self._laptop_online is not None else None
        if probe is None:
            return True  # nobody can say: try, the call itself will tell
        try:
            return bool(await probe(uid))
        except Exception as exc:  # noqa: BLE001 - unknown means "try"
            log.warning("laptop probe failed", extra={"error": type(exc).__name__})
            return True

    async def poll(self, uid: str) -> dict[str, int]:
        """Retry what waits for the laptop, refresh the copy, announce new groups once."""
        photos = self._photos()
        out = {"forgotten": 0, "named": 0, "told": 0, "away": 0}
        if photos is None or not await self._online(uid):
            out["away"] = 1
            return out
        try:
            out["named"] = await photos.retry_pending(uid)  # names first, then what to forget
            if (await self.store.get(uid)).forget_all:
                out["forgotten"] += (await self.forget_all(uid)).forgotten
            for group in (await self.store.get(uid)).forget:
                out["forgotten"] += (await self._forget_one(uid, photos, group)).forgotten
            doc = await self._refresh(uid, photos, await self.store.get(uid))
        except _AWAY:
            out["away"] = 1
            return out
        if doc.forget_all or doc.forget:  # an ask still waits: the laptop went away mid-way
            out["away"] = 1
            return out
        out["told"] = await self._announce(uid, doc)
        return out

    async def _announce(self, uid: str, doc: GroupsDoc) -> int:
        notifier = self._notifier() if self._notifier is not None else None
        waiting = [g.id for g in doc.shown if g.id not in set(doc.told)]
        if not waiting or notifier is None:
            return 0
        new = await self.store.claim_told(uid, waiting)  # claimed before the send: told once
        if not new:
            return 0
        text = ALERT_ONE if len(new) == 1 else ALERT_MANY.format(n=len(new))
        await notifier.notify(uid, Signal(source="home", kind="faces_to_name"), text)
        return len(new)

    # ---- erasure and the audit -----------------------------------------------------------------

    async def purge(self, uid: str) -> None:
        """The cloud's copy only (the laptop's groups are forgotten with `forget_all`)."""
        await self.store.delete(uid)

    async def _record(self, uid: str, tool: str, count: int, detail: str) -> None:
        """Audit: a count only, never a name or an id. It already happened; an outage is logged."""
        if self._audit is None:
            return
        try:
            await self._audit.append(
                agent=AUDIT_AGENT,
                tool=tool,
                risk=ActionRisk.REVERSIBLE,
                outcome="executed",
                args={"count": count},
                detail=f"{detail}: {count}",
            )
        except Exception as exc:  # noqa: BLE001
            log.error("AUDIT WRITE FAILED for face groups", extra={"error": type(exc).__name__})


__all__ = ["OFF", "FaceGroupsService", "Forgotten", "GroupsView"]
