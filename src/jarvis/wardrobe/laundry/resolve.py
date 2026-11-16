# src/jarvis/wardrobe/laundry/resolve.py
"""R13 Part B: answering a review entry (docs/plans/r13-wardrobe.md D11, D5, LND-03, LND-04,
OPS-02), pure.

An entry is answered by a scan, a label or a tap: `these` (these pieces: the ones that went into
the basket, the ones still as they were, or the change that did happen), `none` ("there was no
deposit", or the change didn't happen: back to `back_to`), `moved` (it is somewhere else now:
`found` with the state and place he gives), `dismiss` (a conflict or a stale check noted). A
piece another check holds is never released by this one; a check about several pieces stays open
for the ones not answered yet.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import NamedTuple

from jarvis.wardrobe.laundry import loads, texts
from jarvis.wardrobe.laundry.holds import basket_event, tap
from jarvis.wardrobe.laundry.review import find, put
from jarvis.wardrobe.laundry.store import Change, Entry, LaundryDoc, Outcome, ReviewDoc
from jarvis.wardrobe.model import Event, Piece, WardrobeView
from jarvis.wardrobe.ports import Refused
from jarvis.wardrobe.states import State

_OUTCOMES: Mapping[str, frozenset[str]] = {
    "pending_deposit": frozenset({"these", "none"}),
    "which": frozenset({"these", "none", "dismiss"}),
    "hold": frozenset({"these", "none", "moved"}),
    "conflict": frozenset({"these", "none", "dismiss"}),
    "stale": frozenset({"these", "moved", "dismiss"}),
}


class _Res(NamedTuple):
    events: list[Event]
    laundry: LaundryDoc | None
    left: tuple[str, ...]
    words: str


def _family(e: Entry) -> str:
    """How an entry is answered. Only B's own "which one?" (it carries the step he asked for)
    takes a laundry step; every other rescan (A's "corrected", another part's) is a check: a
    sighting where it is, a new place, or dismissed (review H1: never a default clean return)."""
    if e.kind == "rescan":
        if e.reason == "blind":
            return "hold"
        return "which" if e.reason == "which" and e.step else "stale"
    return "stale" if e.kind == "place" else e.kind


def _chosen(
    chosen: Sequence[str], allowed_ids: Sequence[str], limit: int | None = None
) -> list[str]:
    picked = list(dict.fromkeys(chosen))
    if any(c not in allowed_ids for c in picked):
        raise Refused(texts.NOT_A_CANDIDATE)
    if limit is not None and len(picked) > limit:
        raise Refused(texts.too_many_picked(limit))
    return picked


def _as(p: Piece, state: State | None) -> Piece:
    return p.model_copy(update={"state": state or p.state})


def _pending(
    view: WardrobeView, e: Entry, outcome: str, chosen: Sequence[str], how: str, now: datetime
) -> _Res:
    picked = _chosen(chosen, e.candidates or tuple(view.pieces), max(e.count, 1))
    if outcome == "these" and not picked:
        raise Refused(texts.NOTHING_NAMED)
    ours = {
        pid
        for pid in e.pieces
        if (q := view.pieces.get(pid)) and q.state == "review" and q.hold == "held"
    }
    events = [tap(pid, "released", now, how=how) for pid in e.pieces if pid in ours]
    back: list[Piece] = []
    for pid in picked if outcome == "these" else ():
        p = view.pieces[pid]
        if p.state == "review" and pid not in ours:
            raise Refused(texts.held(p))
        after = _as(p, p.back_to if pid in ours else p.state)
        if after.state in ("ready", "in_use"):
            events.append(basket_event(after, now))
        elif after.state != "in_laundry":
            raise Refused(texts.wrong_state(p, "basket"))
        back.append(p)
    return _Res(events, None, (), texts.done("basket", back) if back else texts.CLOSED)


def _confirmed(
    p: Piece, e: Entry, originals: Mapping[str, Event], how: str, now: datetime
) -> list[Event]:
    """The unverified change he says did happen, recorded again as his (verified) word."""
    out: list[Event] = []
    for eid in e.events:
        orig = originals.get(eid)
        if orig is None or orig.piece != p.id:
            continue
        if orig.kind == "deposited":
            out.append(basket_event(_as(p, p.back_to), now))
        else:
            fields = {k: getattr(orig, k) for k in ("to", "place", "plan", "load", "batch", "due")}
            out.append(tap(p.id, orig.kind, now, how=how, **fields))
    return out


def _hold(
    view: WardrobeView,
    e: Entry,
    outcome: str,
    chosen: Sequence[str],
    to: State | None,
    place: str | None,
    how: str,
    originals: Mapping[str, Event],
    now: datetime,
) -> _Res:
    expected = "blind" if e.kind == "rescan" else e.reason
    targets = _chosen(chosen, e.pieces) or list(e.pieces)
    if outcome == "moved" and to is None:
        raise Refused(texts.MOVED_NEEDS)
    events: list[Event] = []
    for pid in targets:
        p = view.pieces.get(pid)
        if p is None or p.state != "review" or p.hold != expected:
            continue  # answered another way meanwhile
        if outcome == "moved":
            events.append(tap(pid, "found", now, to=to, place=place, how=how))
            continue
        events.append(tap(pid, "released", now, how=how))
        if outcome == "these" and e.reason == "unverified":
            events += _confirmed(p, e, originals, how, now)
    left = tuple(x for x in e.pieces if x not in targets)
    words = texts.partly_checked(len(targets), len(left)) if left else texts.CLOSED
    return _Res(events, None, left, words)


def _stale(
    view: WardrobeView,
    e: Entry,
    outcome: str,
    chosen: Sequence[str],
    place: str | None,
    how: str,
    now: datetime,
) -> _Res:
    if outcome == "dismiss":
        return _Res([], None, (), texts.CLOSED)
    targets = _chosen(chosen, e.candidates) or list(e.candidates)
    events = [
        tap(
            pid, "seen", now, place=place if outcome == "moved" else view.pieces[pid].place, how=how
        )
        for pid in targets
        if pid in view.pieces
    ]
    left = tuple(x for x in e.candidates if x not in targets)
    return _Res(
        events, None, left, texts.partly_checked(len(targets), len(left)) if left else texts.CLOSED
    )


def _which(
    view: WardrobeView,
    laundry: LaundryDoc,
    e: Entry,
    outcome: str,
    chosen: Sequence[str],
    now: datetime,
) -> _Res:
    if e.step is None:  # only B's own "which one?" carries a step: never a default one
        raise Refused(texts.OUTCOME_BAD)
    if outcome != "these":
        return _Res([], None, (), texts.CLOSED)
    picked = _chosen(chosen, e.candidates)
    if not picked:
        raise Refused(texts.NOT_A_CANDIDATE)
    step = loads.plan_step(view, laundry, e.step, picked, load=e.load, place=e.place, now=now)
    return _Res(list(step.events), step.laundry, (), step.words)


def plan_resolve(
    view: WardrobeView,
    laundry: LaundryDoc,
    doc: ReviewDoc,
    entry_id: str,
    outcome: Outcome,
    *,
    pieces: Sequence[str] = (),
    to: State | None = None,
    place: str | None = None,
    how: str = "tap",
    originals: Mapping[str, Event] | None = None,
    now: datetime,
) -> Change:
    e = find(doc, entry_id)
    if e is None:
        raise Refused(texts.ENTRY_GONE)
    fam = _family(e)
    if outcome not in _OUTCOMES[fam] or (
        fam == "hold" and outcome == "none" and e.reason != "unverified"
    ):
        raise Refused(texts.OUTCOME_BAD)
    if fam == "pending_deposit":
        res = _pending(view, e, outcome, pieces, how, now)
    elif fam == "which":
        res = _which(view, laundry, e, outcome, pieces, now)
    elif fam == "hold":
        res = _hold(view, e, outcome, pieces, to, place, how, originals or {}, now)
    elif fam == "stale":
        res = _stale(view, e, outcome, pieces, place, how, now)
    else:
        res = _Res([], None, (), texts.CLOSED)
    field = "candidates" if fam == "stale" else "pieces"
    after = e.model_copy(
        update={field: res.left} if res.left else {"closed_at": now, "outcome": outcome}
    )
    return Change(
        events=tuple(res.events),
        laundry=res.laundry,
        review=put(doc, after),
        words=res.words,
        pieces=tuple(dict.fromkeys(ev.piece for ev in res.events)),
    )


__all__ = ["plan_resolve"]
