# src/jarvis/faces/service.py
"""The Faces panel's engine (R3 D13). Layer 3 over the encrypted registry.

add      needs the consent statement (see `consent.check`); the person starts `consented`. Nobody
         is enrolled by default: the registry starts empty.
enrol    happens at home. A heartbeat's picture counts (`apply_pictures`) move a person between
         `consented` and `enrolled`; the cloud never sees a picture.
remove   state `deleting` at once (the name stops resolving), the bridge is told best-effort; its
         `face_deleted` ack (`ack`) removes the record and leaves an audit entry with a count only.
         A sleeping laptop is told with the next heartbeat reply (`state_part`).
Nothing here is logged beyond counts and class names.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from jarvis.core.guardrails import ActionRisk
from jarvis.faces import consent
from jarvis.faces.models import MAX, NAME_MAX, RELATIONS, Person, State, new_person_id
from jarvis.faces.store import FacesStore, FacesUnavailable
from jarvis.home.ports import (
    Ack,
    BridgeState,
    FacesState,
    Heartbeat,
    HomeCaller,
    HomeUnavailable,
)
from jarvis.logging import get_logger
from jarvis.tools.card import one_line

log = get_logger(__name__)

STATE_PATH = "/bridge/v1/state"
AUDIT_AGENT = "faces"


class PersonRejected(ValueError):
    """A change that is not allowed, in plain words (`code` is stable; `status` the HTTP one)."""

    def __init__(self, code: str, detail: str, *, status: int = 422) -> None:
        super().__init__(detail)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class PersonView:
    id: str
    name: str
    relation: str
    child: bool
    vip: bool
    state: str
    consent_at: str
    consent_version: str
    renewal_due: bool
    pictures: int | None


@dataclass(frozen=True)
class FacesView:
    people: tuple[PersonView, ...]
    total: int
    limit: int


@dataclass(frozen=True)
class Removed:
    person: str
    pushed: bool  # False: the laptop didn't answer; it learns on its next check-in


def _clean_name(value: object) -> str:
    text = one_line(value, NAME_MAX + 1)
    if not text:
        raise PersonRejected("no_name", "Give the person's name.")
    if len(text) > NAME_MAX:
        raise PersonRejected("too_long", f"A name can be at most {NAME_MAX} characters.")
    return text


def _relation(value: object) -> str:
    if value not in RELATIONS:
        raise PersonRejected("bad_relation", "Choose family, friend, helper or other.")
    return str(value)


def _same_name(people: tuple[Person, ...], name: str, *, but: str | None = None) -> None:
    key = name.casefold()
    if any(p.name.casefold() == key and p.id != but for p in people if p.state != "deleting"):
        raise PersonRejected(
            "duplicate_name", "Someone with that name is already added.", status=409
        )


def _now(clock: Callable[[], datetime]) -> str:
    return clock().astimezone(UTC).isoformat()


class FacesService:
    handles = frozenset({"ack", "heartbeat"})

    def __init__(
        self,
        store: FacesStore,
        home: HomeCaller | None = None,
        *,
        audit: Any = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._home = home
        self._audit = audit
        self._clock = clock
        self._last_pictures: dict[str, dict[str, int]] = {}

    # ---- reads -----------------------------------------------------------------------------

    async def state(self, uid: str) -> State:
        return await self._store.load(uid)

    async def view(self, uid: str) -> FacesView:
        state = await self._store.load(uid)
        now = self._clock()
        people = tuple(
            PersonView(
                p.id,
                p.name,
                p.relation,
                p.child,
                p.vip,
                p.state,
                p.consent_at,
                p.consent_version,
                consent.renewal_due(p, now),
                p.images_at_home,
            )
            for p in state.people
        )
        return FacesView(people, len(state.live()), MAX)

    async def state_part(self, uid: str) -> BridgeState:
        """The faces part of the bridge state: consented ids and ids to delete (never names).
        Unreadable: `faces=None`, which means "unchanged" to the bridge."""
        try:
            state = await self._store.load(uid)
        except FacesUnavailable:
            return BridgeState()
        return BridgeState(
            faces=FacesState(
                rev=state.rev,
                people=tuple(p.id for p in state.live()),
                deleting=tuple(p.id for p in state.deleting()),
            )
        )

    async def export(self, uid: str) -> dict[str, Any]:
        """Consent records, no pictures (there are none here)."""
        state = await self._store.load(uid)
        return {"people": [p.to_json() for p in state.live()], "pictures": "only on your laptop"}

    # ---- writes ----------------------------------------------------------------------------

    async def add(
        self,
        uid: str,
        *,
        name: object,
        relation: object,
        child: bool,
        vip: bool,
        given_by: str,
        consent_version: str,
        confirm: object,
    ) -> Person:
        try:
            consent.check(child=child, given_by=given_by, version=consent_version, confirm=confirm)
        except consent.ConsentRejected as exc:
            raise PersonRejected(exc.code, str(exc)) from None
        clean, rel = _clean_name(name), _relation(relation)
        stamp = _now(self._clock)
        person = Person(
            new_person_id(),
            clean,
            rel,
            child,
            bool(vip),
            consent_version,
            given_by,
            stamp,
            "consented",
            stamp,
        )

        def fn(state: State) -> State:
            if len(state.people) >= MAX:
                raise PersonRejected("people_full", f"At most {MAX} people.", status=409)
            _same_name(state.people, clean)
            return State(state.rev, (*state.people, person))

        await self._store.change(uid, fn)
        await self._push(uid)
        return person

    async def update(
        self,
        uid: str,
        person_id: str,
        *,
        name: object = None,
        relation: object = None,
        vip: bool | None = None,
        reconfirm: bool = False,
    ) -> Person:
        """Name, relation and VIP can change; the child mark and the consent statement cannot
        (that needs a new person with new consent). `reconfirm` restarts the consent year."""
        clean = None if name is None else _clean_name(name)
        rel = None if relation is None else _relation(relation)
        stamp = _now(self._clock)
        found: list[Person] = []

        def fn(state: State) -> State:
            current = state.find(person_id)
            if current is None or current.state == "deleting":
                raise PersonRejected("not_found", "There is no such person.", status=404)
            changes: dict[str, Any] = {}
            if clean is not None:
                _same_name(state.people, clean, but=person_id)
                changes["name"] = clean
            if rel is not None:
                changes["relation"] = rel
            if vip is not None:
                changes["vip"] = vip
            if reconfirm:
                changes["consent_at"] = stamp
            new = current.with_(**changes)
            found.append(new)
            return State(state.rev, tuple(new if p.id == person_id else p for p in state.people))

        await self._store.change(uid, fn)
        return found[0]

    async def remove(self, uid: str, person_id: str) -> Removed:
        """Start a delete: the name stops resolving at once; the laptop is told if it answers."""
        stamp = _now(self._clock)

        def fn(state: State) -> State:
            current = state.find(person_id)
            if current is None:
                raise PersonRejected("not_found", "There is no such person.", status=404)
            if current.state == "deleting":
                return state
            gone = current.with_(state="deleting", delete_requested_at=stamp)
            return State(state.rev, tuple(gone if p.id == person_id else p for p in state.people))

        await self._store.change(uid, fn)
        return Removed(person_id, await self._push(uid))

    async def remove_all(self, uid: str) -> int:
        """Privacy -> Faces -> Delete all: every live person starts deleting. Returns how many."""
        stamp = _now(self._clock)
        count: list[int] = []

        def fn(state: State) -> State:
            count.append(len(state.live()))
            return State(
                state.rev,
                tuple(
                    p
                    if p.state == "deleting"
                    else p.with_(state="deleting", delete_requested_at=stamp)
                    for p in state.people
                ),
            )

        await self._store.change(uid, fn)
        await self._push(uid)
        return count[0]

    async def ack(self, uid: str, person_id: str) -> bool:
        """The laptop deleted this person's pictures: the record goes (only a person already
        `deleting` can be removed this way, so a stray ack can never delete a consented person)."""
        removed: list[bool] = []

        def fn(state: State) -> State:
            current = state.find(person_id)
            removed.append(current is not None and current.state == "deleting")
            if not removed[0]:
                return state
            return State(state.rev, tuple(p for p in state.people if p.id != person_id))

        await self._store.change(uid, fn)
        if removed[0]:
            await self._record(uid, "faces_delete_done", 1, "pictures deleted at home")
        return removed[0]

    async def apply_pictures(self, uid: str, counts: dict[str, int]) -> None:
        """A heartbeat's picture counts: pictures -> `enrolled`; none -> back to `consented`."""
        if self._last_pictures.get(uid) == counts:
            return

        def fn(state: State) -> State:
            people = []
            for p in state.people:
                if p.state == "deleting" or p.id not in counts:
                    people.append(p)
                    continue
                n = counts[p.id]
                people.append(p.with_(images_at_home=n, state="enrolled" if n > 0 else "consented"))
            return State(state.rev, tuple(people))

        before = await self._store.load(uid)
        if all(
            p.state == "deleting"
            or p.id not in counts
            or (p.images_at_home == counts[p.id] and (p.state == "enrolled") == (counts[p.id] > 0))
            for p in before.people
        ):
            self._last_pictures[uid] = dict(counts)
            return
        await self._store.change(uid, fn)
        self._last_pictures[uid] = dict(counts)

    # ---- the webhook -----------------------------------------------------------------------

    async def handle(self, uid: str, event: Any) -> None:
        try:
            if isinstance(event, Ack) and event.what == "face_deleted" and event.person:
                await self.ack(uid, event.person)
            elif isinstance(event, Heartbeat) and event.parts.faces is not None:
                await self.apply_pictures(uid, dict(event.parts.faces))
        except (FacesUnavailable, PersonRejected):
            log.warning("faces event not applied")

    # ---- helpers ---------------------------------------------------------------------------

    async def _push(self, uid: str) -> bool:
        """Tell the bridge now (best effort). False: it will learn on its next heartbeat."""
        if self._home is None:
            return False
        try:
            part = await self.state_part(uid)
            if part.faces is None:
                return False
            async with asyncio.timeout(10):
                await self._home.call(
                    uid, "POST", STATE_PATH, part.model_dump(mode="json", exclude_none=True)
                )
        except (HomeUnavailable, TimeoutError):
            return False
        except Exception as exc:  # noqa: BLE001 - the change is saved; the heartbeat retries
            log.warning("faces push failed", extra={"reason": type(exc).__name__})
            return False
        return True

    async def record(self, uid: str, tool: str, count: int, how: str) -> None:
        await self._record(uid, tool, count, how)

    async def _record(self, uid: str, tool: str, count: int, detail: str) -> None:
        """Audit: the count only, never a name. It already happened; an outage is logged."""
        if self._audit is None:
            return
        try:
            await self._audit.append(
                agent=AUDIT_AGENT,
                tool=tool,
                risk=ActionRisk.IRREVERSIBLE,
                outcome="executed",
                args={"count": count},
                detail=f"{detail}: {count}",
            )
        except Exception as exc:  # noqa: BLE001
            log.error("AUDIT WRITE FAILED for faces", extra={"error": type(exc).__name__})


__all__ = [
    "AUDIT_AGENT",
    "FacesService",
    "FacesView",
    "PersonRejected",
    "PersonView",
    "Removed",
]
