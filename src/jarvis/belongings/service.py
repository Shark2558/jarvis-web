# src/jarvis/belongings/service.py
""" "Where did I keep it?" (R2 D11; Layer 3 over the encrypted Layer 7 store).

put      add a thing, or move it: "put X in Y" on an existing thing (same `thing_key`, or one of
         its aliases) is a move; the old place goes into its history (<= 50), and the answer says
         where it was. The same place again only refreshes the date.
where    best match: the exact key first, then BM25 over name + aliases + place (<= 3 candidates).
list / history   <= 50 things; <= 10 moves of one thing (newest first).
remove   a soft delete: a copy `{ref}` goes into Recently deleted first (no copy -> nothing is
         removed), then the thing gets a tombstone. restore clears it in place (same id).
purge    the bin's "Remove now" / sweep: the thing and its history are deleted for good.
wipe     everything (the privacy dashboard).

Every text passes the memory sensitive filter: "IDs go in the Vault; JARVIS doesn't keep passwords
or card numbers". Nothing here is logged beyond counts and class names.
"""

from __future__ import annotations

import asyncio
import builtins
import secrets
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from jarvis.belongings.models import (
    ALIAS_MAX,
    HOLDER_MAX,
    MAX_HISTORY,
    MAX_HOLDERS,
    MAX_LIVE,
    NAME_MAX,
    NOTE_MAX,
    ORIGINS,
    PLACE_MAX,
    THING_ID,
    Holder,
    Move,
    State,
    Thing,
    worse_origin,
)
from jarvis.belongings.store import BelongingsStore, Change
from jarvis.belongings.text import thing_key
from jarvis.logging import get_logger
from jarvis.recall.retrieval import bm25
from jarvis.recall.sensitive import sensitive_reason
from jarvis.recall.text import tokens
from jarvis.tools.card import one_line
from jarvis.undo.models import DeletedItem
from jarvis.undo.service import (
    Gone,
    Restored,
    SnapshotFailed,
    StillThere,
    UndoBin,
    discard_kind,
)

log = get_logger(__name__)

LIST_MAX = 50
CANDIDATES = 3
HISTORY_SHOWN = 10
SENSITIVE_WORDS = "IDs go in the Vault; JARVIS doesn't keep passwords or card numbers."
BIN_TITLE = "A thing you noted"  # the bin shows no name: it is Firestore, in clear
NOT_EXACT = "No thing is noted under exactly that name. Say which one you mean."
NO_BIN = "Removing needs Recently deleted, which isn't available on this server."


class ThingRejected(ValueError):
    """A change that is not allowed, in plain words (`code` is stable; `status` the HTTP one)."""

    def __init__(
        self,
        code: str,
        detail: str,
        *,
        status: int = 422,
        candidates: Sequence[Thing] = (),
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.status = status
        self.candidates = tuple(candidates)  # near matches, for "did you mean"


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class PutResult:
    thing: Thing
    previous_place: str | None
    moved: bool
    created: bool


@dataclass(frozen=True)
class Found:
    best: Thing | None
    candidates: tuple[Thing, ...]


def _limited(value: object, limit: int, what: str) -> str:
    text = one_line(value, limit + 1)
    if len(text) > limit:
        raise ThingRejected("too_long", f"{what} can be at most {limit} characters.")
    return text


def clean_fields(name: object, place: object, note: object = None) -> tuple[str, str, str]:
    n = _limited(name, NAME_MAX, "A name")
    p = _limited(place, PLACE_MAX, "A place")
    t = _limited(note, NOTE_MAX, "A note")
    if not n or not thing_key(n):
        raise ThingRejected("no_name", "Say what you want to remember, for example 'passport'.")
    if not p:
        raise ThingRejected("no_place", "Say where it is, for example 'the blue file'.")
    if sensitive_reason(f"{n}. {p}. {t}"):
        raise ThingRejected("sensitive", SENSITIVE_WORDS)
    return n, p, t


def _matches(t: Thing, key: str) -> bool:
    return t.key == key or key in {thing_key(a) for a in t.aliases}


def _newest(things: Sequence[Thing]) -> list[Thing]:
    return sorted(things, key=lambda t: t.updated_at, reverse=True)


def _doc(t: Thing) -> Counter[str]:
    return Counter(tokens(f"{t.name} {' '.join(t.aliases)}") * 2 + tokens(t.place))


def search(things: Sequence[Thing], query: str, limit: int = CANDIDATES) -> Found:
    """Exact key first; else BM25 over name + aliases + place. Live things only."""
    live = [t for t in things if t.live]
    key = thing_key(query)
    exact = _newest([t for t in live if key and _matches(t, key)])
    if exact:
        rest = [t for t in live if t not in exact]
        return Found(exact[0], tuple([*exact, *_ranked(rest, query)][:limit]))
    ranked = _ranked(live, query)
    return Found(ranked[0] if ranked else None, tuple(ranked[:limit]))


def _ranked(things: Sequence[Thing], query: str) -> list[Thing]:
    q = set(tokens(query))
    if not q or not things:
        return []
    scores = bm25([_doc(t) for t in things], q)
    pairs = [(s, t) for s, t in zip(scores, things, strict=True) if s > 0]
    pairs.sort(key=lambda p: (p[0], p[1].updated_at), reverse=True)
    return [t for _, t in pairs]


class BelongingsService:
    def __init__(
        self,
        store: BelongingsStore,
        undo: UndoBin | None = None,
        *,
        clock: Any = _now,
    ) -> None:
        self.store = store
        self.undo = undo
        self._clock = clock

    def _stamp(self) -> str:
        return str(self._clock().isoformat())

    # ---- reading ---------------------------------------------------------------------------

    async def state(self, uid: str) -> State:
        return await self.store.load(uid)

    async def where(self, uid: str, query: str) -> tuple[Found, State]:
        state = await self.store.load(uid)
        return search(state.things, query), state

    async def list(
        self, uid: str, *, holder: str | None = None, q: str | None = None, limit: int = LIST_MAX
    ) -> tuple[list[Thing], State]:
        state = await self.store.load(uid)
        things = state.live()
        if holder:
            hid = next(
                (h.id for h in state.holders if h.label.casefold() == holder.casefold()), "-"
            )
            things = [t for t in things if t.holder_id == hid]
        if q and q.strip():
            things = list(search(things, q, limit).candidates)
        else:
            things = _newest(things)
        return things[:limit], state

    async def history(self, uid: str, ref: str) -> tuple[Thing, builtins.list[Move], State]:
        state = await self.store.load(uid)
        thing = self._resolve(state, ref)
        moves = await self.store.history(uid, thing.id)
        return thing, list(reversed(moves))[:HISTORY_SHOWN], state

    @staticmethod
    def resolve_exact(state: State, ref: str) -> Thing:
        """The thing a change would touch (id, exact key or alias), or `ThingRejected`."""
        return BelongingsService._resolve(state, ref, exact=True)

    @staticmethod
    def _resolve(state: State, ref: str, *, exact: bool = False) -> Thing:
        """A live thing by id or name. Reads may take the best match; a change (`exact`) takes
        only an id, the exact key or an alias, else it refuses and offers the near matches."""
        if isinstance(ref, str) and THING_ID.fullmatch(ref):
            found = state.get(ref)
            if found is not None and found.live:
                return found
        elif exact:
            key = thing_key(ref)
            hits = _newest([t for t in state.live() if key and _matches(t, key)])
            if hits:
                return hits[0]
            near = search(state.things, ref).candidates if isinstance(ref, str) else ()
            if near:
                raise ThingRejected("not_exact", NOT_EXACT, status=409, candidates=near)
        else:
            best = search(state.things, ref).best
            if best is not None:
                return best
        raise ThingRejected("not_found", "Nothing is noted under that name.", status=404)

    # ---- writing ---------------------------------------------------------------------------

    async def put(
        self,
        uid: str,
        name: object,
        place: object,
        *,
        note: object = None,
        holder: object = None,
        origin: str = "typed",
    ) -> PutResult:
        n, p, t = clean_fields(name, place, note)
        if origin not in ORIGINS:
            raise ThingRejected("bad_origin", "Unknown origin.")
        h = _limited(holder, HOLDER_MAX, "A holder") if holder else ""
        seen: list[PutResult] = []

        def fn(state: State) -> Change:
            now = self._stamp()
            state, hid = _holder(state, h)
            key = thing_key(n)
            old = next(iter(_newest([x for x in state.live() if _matches(x, key)])), None)
            if old is None:
                if len(state.live()) >= MAX_LIVE:
                    raise ThingRejected(
                        "things_full",
                        f"You can note up to {MAX_LIVE} things. Remove one first.",
                        status=409,
                    )
                thing = Thing(f"t_{secrets.token_hex(6)}", n, key, p, now, origin, (), t, hid)
                seen.append(PutResult(thing, None, False, True))
                return Change(state.with_thing(thing))
            same = old.place.casefold() == p.casefold()
            move = () if same else ((old.id, Move(old.place, old.updated_at, now, old.origin)),)
            thing = old.moved(
                place=p if not same else old.place,
                note=t or ("" if not same else old.note),
                holder_id=hid or old.holder_id,
                origin=worse_origin(old.origin, origin),  # review S3: never vouches for old text
                updated_at=now,
                moves=min(old.moves + len(move), MAX_HISTORY),
            )
            seen.append(PutResult(thing, None if same else old.place, not same, False))
            return Change(state.with_thing(thing), move)

        await self.store.change(uid, fn)
        return seen[-1]

    async def update(
        self,
        uid: str,
        ref: str,
        *,
        name: object = None,
        place: object = None,
        note: object = None,
        holder: object = None,
        adopt: bool = False,
    ) -> PutResult:
        """The panel's edit: rename, move, change the note or the holder of one thing. An edit
        keeps the thing's origin (a voice or outside line stays so); only `adopt=True` (the
        owner ticked "This is mine" in the panel) makes it his own (review S3)."""
        seen: list[PutResult] = []
        h = _limited(holder, HOLDER_MAX, "A holder") if holder else ""

        def fn(state: State) -> Change:
            old = self._resolve(state, ref, exact=True)
            n, p, t = clean_fields(
                old.name if name is None else name,
                old.place if place is None else place,
                old.note if note is None else note,
            )
            state, hid = _holder(state, h)
            now = self._stamp()
            moved = p.casefold() != old.place.casefold()
            move = ((old.id, Move(old.place, old.updated_at, now, old.origin)),) if moved else ()
            thing = old.moved(
                name=n,
                key=thing_key(n),
                place=p,
                note=t,
                holder_id=hid or old.holder_id,
                origin="typed" if adopt else old.origin,
                updated_at=now,
                moves=min(old.moves + len(move), MAX_HISTORY),
            )
            seen.append(PutResult(thing, old.place if moved else None, moved, False))
            return Change(state.with_thing(thing), move)

        await self.store.change(uid, fn)
        return seen[-1]

    async def remove(
        self,
        uid: str,
        ref: str,
        *,
        session_id: str | None = None,
        trace_id: str | None = None,
    ) -> tuple[Thing, DeletedItem]:
        """Soft delete with a copy in Recently deleted first. The error is plain words."""
        if self.undo is None:
            raise ThingRejected("no_bin", NO_BIN, status=503)
        state = await self.store.load(uid)
        thing = self._resolve(state, ref, exact=True)
        stamp = self._stamp()  # tells this delete from any later one of the same thing
        try:
            kept = await self.undo.keep(
                uid,
                "thing",
                BIN_TITLE,
                {"ref": thing.id, "deleted_at": stamp},
                owner_authored=thing.origin != "outside",
                session_id=session_id,
                trace_id=trace_id,
            )
        except SnapshotFailed as exc:
            raise ThingRejected("not_kept", str(exc), status=503) from None

        def fn(cur: State) -> Change:
            t = cur.get(thing.id)
            if t is None or not t.live:
                raise ThingRejected("not_found", "Nothing is noted under that name.", status=404)
            return Change(cur.with_thing(t.moved(deleted_at=stamp)))

        try:
            await self.store.change(uid, fn)
        except Exception:
            await self.undo.discard(uid, kept.id)
            raise
        return thing, kept

    # ---- the bin's Restorer and Purger -----------------------------------------------------

    @staticmethod
    def _ref(item: DeletedItem) -> str:
        ref = item.snapshot.get("ref")
        if not isinstance(ref, str) or not THING_ID.fullmatch(ref):
            raise Gone()
        return ref

    async def restore(self, uid: str, item: DeletedItem, *, outside: bool = False) -> Restored:
        """In place (same id). A thing removed for good (purged, or wiped) is `Gone`."""
        ref = self._ref(item)

        def fn(state: State) -> Change:
            t = state.get(ref)
            if t is None:
                raise Gone()
            if t.live:
                raise StillThere("That thing is still in your list.")
            back = t.moved(deleted_at=None, origin="outside" if outside else t.origin)
            return Change(state.with_thing(back))

        await self.store.change(uid, fn)
        return Restored(new_id=ref)

    async def purge(self, uid: str, item: DeletedItem) -> None:
        """Delete the thing and its history for good. Safe to repeat. Only the delete this entry
        recorded is purged: a thing that was restored (or deleted again since) is left alone, so
        an old entry that expires can never destroy a live thing."""
        ref = self._ref(item)
        stamp = item.snapshot.get("deleted_at")

        def fn(state: State) -> Change:
            t = state.get(ref)
            if t is None or t.live or (isinstance(stamp, str) and t.deleted_at != stamp):
                return Change(state)
            return Change(state.without(ref), (), (ref,))

        await self.store.change(uid, fn)

    async def wipe(self, uid: str) -> int:
        """Everything of this owner's: the things, their histories and the bin entries of kind
        thing (`discard_kind`, shared with notes and the vault; best effort)."""
        count = await self.store.wipe(uid)
        await discard_kind(self.undo, uid, "thing")
        return count

    # ---- export ----------------------------------------------------------------------------

    async def export(self, uid: str) -> dict[str, Any]:
        state = await self.store.load(uid)
        live = state.live()
        histories = await asyncio.gather(*(self.store.history(uid, t.id) for t in live))
        return {
            "things": [
                {
                    "name": t.name,
                    "place": t.place,
                    "note": t.note,
                    "holder": state.holder_label(t.holder_id),
                    "updated_at": t.updated_at,
                    "history": [m.to_json() for m in moves],
                }
                for t, moves in zip(live, histories, strict=True)
            ]
        }


def _holder(state: State, label: str) -> tuple[State, str | None]:
    """The holder id for `label` (made on first use, <= 12); no label -> no holder."""
    if not label:
        return state, None
    found = next((h for h in state.holders if h.label.casefold() == label.casefold()), None)
    if found is not None:
        return state, found.id
    if len(state.holders) >= MAX_HOLDERS:
        raise ThingRejected(
            "holders_full", f"At most {MAX_HOLDERS} people can be listed.", status=409
        )
    h = Holder(f"h_{secrets.token_hex(4)}", label)
    return State(state.rev, (*state.holders, h), state.things), h.id


__all__ = [
    "ALIAS_MAX",
    "BelongingsService",
    "Found",
    "PutResult",
    "ThingRejected",
    "clean_fields",
    "search",
]
