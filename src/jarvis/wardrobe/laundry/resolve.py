# src/jarvis/wardrobe/laundry/resolve.py
"""R13 Part B: answering a review entry (docs/plans/r13-wardrobe.md D11, D5, LND-03, LND-04,
OPS-02), pure.

An entry is answered by a scan, a label or a tap: `these` (these pieces: the ones that went into
the basket, the ones still as they were, or the change that did happen), `none` ("there was no
deposit", or the change didn't happen: back to `back_to`), `moved` (it is somewhere else now:
`found` with the state and place he gives; never to an outside laundry, which only a send-out
with its batch does), `dismiss` (a conflict or a stale check noted). A piece another check holds
is never released by this one; a check about several pieces stays open for the ones not
answered yet.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import NamedTuple

from jarvis.wardrobe.laundry import blind, loads, providers, texts
from jarvis.wardrobe.laundry.answers import OUTCOMES, family
from jarvis.wardrobe.laundry.holds import basket_event, tap
from jarvis.wardrobe.laundry.review import find_open, put
from jarvis.wardrobe.laundry.store import Change, Entry, LaundryDoc, Outcome, ReviewDoc
from jarvis.wardrobe.model import Event, Piece, WardrobeView
from jarvis.wardrobe.ports import Refused
from jarvis.wardrobe.states import State


class _Ask(NamedTuple):
    """One answer: what he said, the pieces he picked, where to, how he checked, and when."""

    outcome: str
    chosen: Sequence[str]
    to: State | None
    place: str | None
    how: str
    originals: Mapping[str, Event]
    now: datetime


class _Res(NamedTuple):
    events: list[Event]
    laundry: LaundryDoc | None
    left: tuple[str, ...]
    words: str
    review: ReviewDoc | None = None  # other entries this answer changed (a blind check's list)


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


def _pending(view: WardrobeView, doc: ReviewDoc, e: Entry, a: _Ask) -> _Res:
    picked = _chosen(a.chosen, e.candidates or tuple(view.pieces), max(e.count, 1))
    if a.outcome == "these" and not picked:
        raise Refused(texts.NOTHING_NAMED)
    ours = [
        pid
        for pid in e.pieces
        if (q := view.pieces.get(pid)) and q.state == "review" and q.hold == "held"
    ]
    events: list[Event] = []
    queue = doc
    for pid in ours:  # this check's holds go; one a blind check waits for is held again (M4)
        events.append(tap(pid, "released", a.now, how=a.how))
        if a.outcome != "these" or pid not in picked:
            made, queue = blind.rehold(view, queue, pid, e.id, a.now)
            events += made
    back: list[Piece] = []
    for pid in picked if a.outcome == "these" else ():
        p = view.pieces[pid]
        if p.state == "review" and pid not in ours:
            raise Refused(texts.held(p))
        after = _as(p, p.back_to if pid in ours else p.state)
        if after.state in ("ready", "in_use"):
            events.append(basket_event(after, a.now))
        elif after.state != "in_laundry":
            raise Refused(texts.wrong_state(p, "basket"))
        queue = blind.settle(queue, pid, e.id, a.now)  # his word: verified
        back.append(p)
    words = texts.done("basket", back) if back else texts.CLOSED
    return _Res(events, None, (), words, queue if queue != doc else None)


def _confirmed(p: Piece, a: _Ask) -> list[Event]:
    """The unverified change he says did happen, recorded again as his (verified) word."""
    out: list[Event] = []
    for orig in a.originals.values():
        if orig.piece != p.id:
            continue
        if orig.kind == "deposited":
            out.append(basket_event(_as(p, p.back_to), a.now))
        else:
            fields = {k: getattr(orig, k) for k in ("to", "place", "plan", "load", "batch", "due")}
            out.append(tap(p.id, orig.kind, a.now, how=a.how, **fields))
    return out


def _hold(view: WardrobeView, laundry: LaundryDoc, doc: ReviewDoc, e: Entry, a: _Ask) -> _Res:
    """A hold is matched on the PIECE's own hold, never the entry's reason (A's sweep repairs an
    entry with reason "sweep"): `none` only when each piece's hold is an unconfirmed change. A
    piece he says is home from the shop comes off its batch (review M3)."""
    targets = _chosen(a.chosen, e.pieces) or list(e.pieces)
    if not targets and e.waiting:
        raise Refused(texts.WAITS_OTHER)
    if a.outcome == "moved" and a.to is None:
        raise Refused(texts.MOVED_NEEDS)
    if a.to == "with_provider":
        raise Refused(texts.NOT_TO_SHOP)
    live = [p for pid in targets if (p := view.pieces.get(pid)) and p.state == "review" and p.hold]
    if a.outcome == "none" and any(p.hold != "unverified" for p in live):
        raise Refused(texts.OUTCOME_BAD)
    events: list[Event] = []
    out, queue = laundry, doc
    for p in live:  # a piece no longer held was answered another way meanwhile
        if a.outcome == "moved":
            events.append(tap(p.id, "found", a.now, to=a.to, place=a.place, how=a.how))
            if p.back_to == "with_provider":
                out = providers.mark_back(out, p.id, a.now)
            queue = blind.settle(queue, p.id, e.id, a.now)
            continue
        events.append(tap(p.id, "released", a.now, how=a.how))
        if a.outcome == "these" and p.hold == "unverified":
            events += _confirmed(p, a)
            queue = blind.settle(queue, p.id, e.id, a.now)
        else:  # back as it was, unverified: a blind check that waits for it holds it again
            made, queue = blind.rehold(view, queue, p.id, e.id, a.now)
            events += made
    left = tuple(x for x in e.pieces if x not in targets)
    changed, also = (out if out != laundry else None), (queue if queue != doc else None)
    if left or e.waiting:
        words = texts.partly_checked(len(targets), len(left) + len(e.waiting))
        return _Res(events, changed, left, words, also)
    return _Res(events, changed, (), texts.CLOSED if live else texts.NOTHING_LEFT, also)


def _stale(view: WardrobeView, e: Entry, a: _Ask) -> _Res:
    if a.outcome == "dismiss":
        return _Res([], None, (), texts.CLOSED)
    targets = _chosen(a.chosen, e.candidates) or list(e.candidates)
    events = [
        tap(pid, "seen", a.now, place=a.place if a.outcome == "moved" else p.place, how=a.how)
        for pid in targets
        if (p := view.pieces.get(pid)) is not None
    ]
    left = tuple(x for x in e.candidates if x not in targets)
    words = texts.partly_checked(len(targets), len(left)) if left else texts.CLOSED
    return _Res(events, None, left, words)


def _which(view: WardrobeView, laundry: LaundryDoc, e: Entry, a: _Ask) -> _Res:
    if e.step is None:  # only B's own "which one?" carries a step: never a default one
        raise Refused(texts.OUTCOME_BAD)
    if a.outcome != "these":
        return _Res([], None, (), texts.CLOSED)
    picked = _chosen(a.chosen, e.candidates)
    if not picked:
        raise Refused(texts.NOT_A_CANDIDATE)
    step = loads.plan_step(view, laundry, e.step, picked, load=e.load, place=e.place, now=a.now)
    return _Res(list(step.events), step.laundry, (), step.words)


def _answer(
    view: WardrobeView, laundry: LaundryDoc, doc: ReviewDoc, e: Entry, fam: str, a: _Ask
) -> _Res:
    if fam == "pending_deposit":
        return _pending(view, doc, e, a)
    if fam == "which":
        return _which(view, laundry, e, a)
    if fam == "hold":
        return _hold(view, laundry, doc, e, a)
    if fam == "stale":
        return _stale(view, e, a)
    return _Res([], None, (), texts.CLOSED)


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
    e = find_open(doc, entry_id)
    if place is not None and place not in view.places:  # review L10, as `move` checks it
        raise Refused(texts.UNKNOWN_PLACE)
    fam = family(e)
    if outcome not in OUTCOMES[fam]:
        raise Refused(texts.OUTCOME_BAD)
    ask = _Ask(outcome, pieces, to, place, how, originals or {}, now)
    res = _answer(view, laundry, doc, e, fam, ask)
    field = "candidates" if fam == "stale" else "pieces"
    if res.left or (fam == "hold" and e.waiting):  # a blind check still waits for some (M4)
        after = e.model_copy(update={field: res.left})
    else:
        after = e.model_copy(update={"closed_at": now, "outcome": outcome})
    return Change(
        events=tuple(res.events),
        laundry=res.laundry,
        review=put(res.review or doc, after),
        words=res.words,
        pieces=tuple(dict.fromkeys(ev.piece for ev in res.events)),
    )


__all__ = ["plan_resolve"]
