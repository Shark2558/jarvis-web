# src/jarvis/wardrobe/laundry/holds.py
"""R13 Part B: deposits and holds (docs/plans/r13-wardrobe.md D5 LND-02, LND-03, D7 LND-04, D20).

- `tap(...)`: one event B records from his tap (source `tap`, verified, the server's now: one
  phone-clock rule, plan review M1: B never sends a device time, so nothing B writes needs `sent`).
- `admit(event)`: LND-02, now the contract's (`wardrobe.model.admit`, applied by the store to every
  incoming event); re-exported here. A deposit exists only when he presses "Put in laundry".
- `plausible(view, category, now)`: LND-03. For "and N more I couldn't show": the pieces of that
  category he is wearing or wore in the last 24 hours (never a guess beyond them).
- `match(view, query)`: his words for a piece, matched strictly (every word he said must be one
  of the piece's own: its label, colour, type and pattern words); several matches are never a
  guess (a pending deposit for the basket, a "which one?" entry otherwise).
- `hold_events(pieces, kind, now)`: the ONLY place a hold is made (`held` for a pending deposit,
  `blind` for a blind period). The eval's negative control ("holds off") replaces it.
- `plan_basket(...)`: LND-01, LND-03, LND-04, plan review H1: a worn piece into the basket
  closes its wear (`wear_done` to In laundry, its plan named), so wearing a planned piece is
  never a change for that plan.
Pure: no I/O, no clock (the time is passed in).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, Literal

from jarvis.belongings.text import thing_key
from jarvis.wardrobe.laundry import texts
from jarvis.wardrobe.laundry.store import Change, Entry, new_entry_id
from jarvis.wardrobe.model import Event, Evidence, Piece, WardrobeView, admit, new_id
from jarvis.wardrobe.ports import Refused
from jarvis.wardrobe.states import EventKind, State, allowed, target_of

WORN_WINDOW = timedelta(hours=24)
BASKET_FROM: frozenset[State] = frozenset({"ready", "in_use"})
_DROP = frozenset({"my", "the", "a", "an", "one", "pair", "of", "is", "in", "that", "this"})
_TYPE_WORDS = {"t_shirt": ("tshirt", "tee"), "dress_shoe": ("dress", "shoe")}


def tap(pid: str, kind: EventKind, now: datetime, **fields: Any) -> Event:
    """A verified event from his tap at the server's now (`how`: tap unless a scan or label)."""
    how = fields.pop("how", "tap")
    return Event.model_validate(
        {
            "id": new_id("we"),
            "piece": pid,
            "kind": kind,
            "at": now,
            "recorded": now,
            "source": "tap",
            "verified": True,
            "evidence": Evidence.model_validate({"how": how}),
            **{k: v for k, v in fields.items() if v is not None},
        }
    )


def plausible(
    view: WardrobeView, category: str | None, now: datetime, *, exclude: Sequence[str]
) -> tuple[str, ...]:
    """LND-03: the pieces of `category` he is wearing, or wore within the last 24 hours and are
    Ready again; never one already in the laundry, held, out or archived."""

    def worn(p: Piece) -> bool:
        if p.state == "in_use":
            return True
        return p.state == "ready" and p.last_worn is not None and now - p.last_worn <= WORN_WINDOW

    return tuple(
        sorted(
            p.id
            for p in view.active()
            if p.category == category and p.id not in exclude and worn(p)
        )
    )


def _words(text: str) -> set[str]:
    return set(
        thing_key(text.casefold().replace("t-shirt", "tshirt").replace("t shirt", "tshirt")).split()
    )


def piece_words(p: Piece) -> set[str]:
    out = _words(p.label) if p.label else set()
    for colour in (p.colour, p.second):
        if colour:
            out |= _words(colour.replace("_", " "))
    out |= set(_TYPE_WORDS.get(p.type, ())) or _words(p.type.replace("_", " "))
    if p.pattern:
        out |= _words(p.pattern)
    return out


def match(view: WardrobeView, query: str) -> tuple[Piece, ...]:
    """Every active piece whose own words include every word he said (order by id)."""
    wanted = _words(query) - _DROP
    if not wanted:
        return ()
    return tuple(sorted((p for p in view.active() if wanted <= piece_words(p)), key=lambda p: p.id))


def fits(kind: EventKind, piece: Piece) -> bool:
    """May `kind` move this piece now, or is it a second record of where it already is?"""
    if allowed(kind, piece.state):
        return True
    keep = kind in ("lifted", "seen")
    return not keep and target_of(kind, piece.state) == piece.state


def hold_events(
    pieces: Sequence[Piece], kind: Literal["held", "blind"], now: datetime
) -> tuple[Event, ...]:
    """The one maker of holds (the eval's control turns it off)."""
    return tuple(tap(p.id, kind, now) for p in pieces)


def basket_event(piece: Piece, now: datetime, place: str | None = None) -> Event:
    """Into the basket; a piece he is wearing closes its wear for its plan (H1)."""
    if piece.state == "in_use":
        return tap(piece.id, "wear_done", now, to="in_laundry", plan=piece.wear, place=place)
    return tap(piece.id, "deposited", now, place=place)


def check_basket(piece: Piece) -> None:
    if piece.state == "review":
        raise Refused(texts.held(piece))
    if piece.state == "with_provider":
        raise Refused(texts.with_provider(piece))
    if piece.state not in BASKET_FROM and piece.state != "in_laundry":
        raise Refused(texts.wrong_state(piece, "basket"))


def check_one_of(piece: Piece) -> None:
    """A "one of these" candidate: Ready or In use (one held elsewhere is skipped by the caller)."""
    if piece.state == "with_provider":
        raise Refused(texts.with_provider(piece))
    if piece.state not in BASKET_FROM:
        raise Refused(texts.wrong_state(piece, "basket"))


def pending(
    view: WardrobeView,
    candidates: Sequence[str],
    now: datetime,
    *,
    count: int,
    category: str | None = None,
) -> tuple[Entry, tuple[Event, ...]]:
    """A pending deposit with no piece id: its entry, and holds for its candidates that could go
    into the basket (Ready, In use); one already waiting for another check stays that check's."""
    free = [view.pieces[c] for c in candidates if view.pieces[c].state in BASKET_FROM]
    holds = hold_events(free, "held", now)
    entry = Entry(
        id=new_entry_id(),
        kind="pending_deposit",
        reason="pending",
        pieces=tuple(p.id for p in free),
        candidates=tuple(candidates),
        events=tuple(e.id for e in holds),
        count=count,
        step="basket",
        category=category,  # type: ignore[arg-type]
        opened_at=now,
    )
    return entry, holds


def plan_basket(
    view: WardrobeView,
    ids: Sequence[str],
    *,
    one_of: Sequence[str] = (),
    more: int = 0,
    category: str | None = None,
    place: str | None = None,
    now: datetime,
) -> Change:
    sure = [view.pieces[i] for i in ids]
    for p in sure:
        check_basket(p)
    for c in one_of:  # review M3: only a piece that could go in; never one at the shop
        if view.pieces[c].state != "review":
            check_one_of(view.pieces[c])
    events = [basket_event(p, now, place) for p in sure]
    entries: list[Entry] = []
    if one_of:
        entry, holds = pending(view, one_of, now, count=1)
        entries.append(entry)
        events += holds
    if more:
        found = plausible(view, category, now, exclude=ids)
        entry, holds = pending(view, found, now, count=more, category=category)
        entries.append(entry)
        events += holds
    return Change(
        events=tuple(events),
        entries=tuple(entries),
        words=_basket_words(sure, one_of, more),
        pieces=tuple(p.id for p in sure) + tuple(one_of),
        entry=entries[0].id if entries else None,
    )


def _basket_words(sure: Sequence[Piece], one_of: Sequence[str], more: int) -> str:
    parts = [texts.done("basket", sure)] if sure else []
    if one_of:
        parts.append(texts.ambiguous(len(one_of), basket=True))
    if more:
        tail = texts.more_waiting(more)
        parts.append(tail if sure or one_of else f"Noted: {tail}")
    return " ".join(parts)


STEP_FROM: Mapping[str, frozenset[State]] = {
    "basket": BASKET_FROM,
    "lifted": frozenset({"in_laundry"}),
    "load": frozenset({"in_laundry"}),
    "washing": frozenset({"in_laundry"}),
    "drying": frozenset({"washing"}),
    "prep": frozenset({"washing", "drying"}),
    "ready": frozenset({"in_laundry", "washing", "drying", "needs_prep"}),
}
NONE_FIT = "No piece that matches can take that step right now."


def known(view: WardrobeView, ids: Sequence[str]) -> list[str]:
    for pid in ids:
        p = view.pieces.get(pid)
        if p is None or p.merged_into is not None:
            raise Refused(texts.UNKNOWN_PIECE)
    return list(dict.fromkeys(ids))


def resolve_query(view: WardrobeView, step: str, query: str) -> tuple[str, ...]:
    """His words for the pieces: those that can take this step; never a guess between them."""
    matched = match(view, query)
    if not matched:
        raise Refused(texts.NO_MATCH)
    fit = tuple(p.id for p in matched if p.state in STEP_FROM[step])
    if fit:
        return fit
    if len(matched) == 1:
        return (matched[0].id,)  # its own refusal says why
    raise Refused(NONE_FIT)


__all__ = [
    "BASKET_FROM",
    "NONE_FIT",
    "STEP_FROM",
    "WORN_WINDOW",
    "admit",
    "basket_event",
    "check_basket",
    "check_one_of",
    "fits",
    "hold_events",
    "known",
    "match",
    "pending",
    "piece_words",
    "plan_basket",
    "plausible",
    "resolve_query",
    "tap",
]
