# src/jarvis/wardrobe/laundry/loads.py
"""R13 Part B: the steps after the basket (docs/plans/r13-wardrobe.md D3, D11).

- lifted (LND-06): out of the basket to a sorting place; still In laundry, still unavailable.
- load / washing (LND-07): a load holds only the confirmed ids he names; the load and their
  `load_started` events are written in ONE commit, so a load never says Washing while its pieces
  are In laundry.
- drying, prep (LND-08, LND-10): each step moves only the pieces named (or, with only a load, its
  washing pieces: the phone form of the washer's "finished"); a step on a piece not in that load is
  refused. "Needs pressing" from the machine is dried, then needs prep.
- ready (LND-11, LND-12): a clean return keeps the id and takes the place he names; a load closes
  when every piece is back (or has left the laundry another way).
Pure: no I/O, no clock. Open loads at most 50; closed ones are kept 90 days.
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Literal

from jarvis.wardrobe.http import LoadView
from jarvis.wardrobe.laundry import texts
from jarvis.wardrobe.laundry.holds import fits, tap
from jarvis.wardrobe.laundry.store import Change, LaundryDoc, Load
from jarvis.wardrobe.model import Event, Piece, WardrobeView
from jarvis.wardrobe.ports import Refused
from jarvis.wardrobe.states import EventKind, State

MAX_OPEN = 50
MAX_PIECES = 50
KEEP = timedelta(days=90)
IN_LAUNDRY: frozenset[State] = frozenset({"in_laundry", "washing", "drying", "needs_prep"})
STEPS = ("lifted", "load", "washing", "drying", "prep", "ready")
WHOLE_LOAD = frozenset({"drying", "prep", "ready"})  # a load alone names its pieces
_KIND: dict[str, EventKind] = {
    "lifted": "lifted",
    "load": "load_started",
    "washing": "load_started",
    "drying": "dried",
    "ready": "returned",
}
_WHOLE_FROM: dict[str, frozenset[State]] = {
    "drying": frozenset({"washing"}),
    "prep": frozenset({"washing", "drying"}),
    "ready": frozenset({"washing", "drying", "needs_prep"}),
}


def new_load_id() -> str:
    return f"ld_{secrets.token_hex(4)}"


def open_loads(doc: LaundryDoc) -> tuple[Load, ...]:
    return tuple(x for x in doc.loads if x.closed_at is None)


def find(doc: LaundryDoc, load_id: str | None) -> Load | None:
    return next((x for x in open_loads(doc) if x.id == load_id), None)


def load_of(doc: LaundryDoc, pid: str) -> Load | None:
    return next((x for x in open_loads(doc) if pid in x.pieces and pid not in x.back), None)


def remaining(load: Load, view: WardrobeView) -> tuple[str, ...]:
    """Pieces of the load not back yet and still in the laundry."""
    return tuple(
        p
        for p in load.pieces
        if p not in load.back and p in view.pieces and view.pieces[p].state in IN_LAUNDRY
    )


def step_of(load: Load, view: WardrobeView) -> Literal["washing", "drying", "needs_prep", "done"]:
    states = {view.pieces[p].state for p in remaining(load, view)}
    for state in ("washing", "drying", "needs_prep"):
        if state in states:
            return state
    return "washing" if "in_laundry" in states else "done"


def load_view(load: Load, view: WardrobeView) -> LoadView:
    return LoadView(
        id=load.id, started_at=load.started_at, pieces=load.pieces, step=step_of(load, view)
    )


def _replace(doc: LaundryDoc, load: Load) -> LaundryDoc:
    loads = [load if x.id == load.id else x for x in doc.loads]
    if all(x.id != load.id for x in doc.loads):
        loads.append(load)
    return doc.model_copy(update={"loads": tuple(loads)})


def settle(doc: LaundryDoc, view: WardrobeView, now: datetime) -> LaundryDoc:
    """Close every open load whose pieces are all back or out of the laundry."""
    out = doc
    for x in open_loads(doc):
        if not remaining(x, view):
            out = _replace(out, x.model_copy(update={"closed_at": now}))
    return out


def prune(doc: LaundryDoc, now: datetime) -> LaundryDoc:
    keep = tuple(x for x in doc.loads if x.closed_at is None or now - x.closed_at <= KEEP)
    return doc.model_copy(update={"loads": keep})


def _check(piece: Piece, step: str) -> None:
    if piece.state == "review":
        raise Refused(texts.held(piece))
    if piece.state == "with_provider":
        raise Refused(texts.with_provider(piece))
    if step in ("load", "washing"):
        ok = piece.state == "in_laundry"
    elif step == "prep":
        ok = piece.state in ("washing", "drying", "needs_prep")
    else:
        ok = fits(_KIND[step], piece)
    if not ok:
        raise Refused(texts.wrong_state(piece, step))


def _events(
    piece: Piece, step: str, now: datetime, load: str | None, place: str | None
) -> list[Event]:
    if step == "prep":
        first = [tap(piece.id, "dried", now, load=load)] if piece.state == "washing" else []
        return [*first, tap(piece.id, "needs_prep", now, load=load)]
    keep_place = place if step in ("lifted", "ready") else None
    return [tap(piece.id, _KIND[step], now, load=load, place=keep_place)]


def _pieces(
    view: WardrobeView, doc: LaundryDoc, step: str, ids: Sequence[str], load_id: str | None
) -> list[Piece]:
    load = find(doc, load_id) if load_id else None
    if load_id and load is None:
        raise Refused(texts.NO_LOAD)
    if load is not None and not ids and step in WHOLE_LOAD:
        ids = [p for p in remaining(load, view) if view.pieces[p].state in _WHOLE_FROM[step]]
    if not ids:
        raise Refused(texts.NOTHING_NAMED)
    pieces = [view.pieces[i] for i in dict.fromkeys(ids)]
    if load is not None and step in WHOLE_LOAD:
        for p in pieces:
            if p.id not in load.pieces or p.id in load.back:
                raise Refused(texts.not_in_load(p))
    return pieces


def _start(
    doc: LaundryDoc, pieces: Sequence[Piece], load_id: str | None, now: datetime
) -> tuple[LaundryDoc, Load]:
    ids = tuple(p.id for p in pieces)
    if load_id:
        load = find(doc, load_id)
        if load is None:
            raise Refused(texts.NO_LOAD)
        load = load.model_copy(update={"pieces": tuple(dict.fromkeys(load.pieces + ids))})
    else:
        if len(open_loads(doc)) >= MAX_OPEN:
            raise Refused(texts.TOO_MANY_LOADS)
        load = Load(id=new_load_id(), started_at=now, pieces=ids)
    if len(load.pieces) > MAX_PIECES:
        raise Refused(texts.TOO_MANY_LOADS)
    return _replace(doc, load), load


def _returned(doc: LaundryDoc, pieces: Sequence[Piece], now: datetime) -> LaundryDoc:
    out = doc
    for p in pieces:
        load = load_of(out, p.id)
        if load is not None:
            out = _replace(out, load.model_copy(update={"back": (*load.back, p.id)}))
    return out


def plan_step(
    view: WardrobeView,
    doc: LaundryDoc,
    step: str,
    ids: Sequence[str],
    *,
    load: str | None = None,
    place: str | None = None,
    now: datetime,
) -> Change:
    pieces = _pieces(view, doc, step, ids, load)
    for p in pieces:
        _check(p, step)
    new_doc, load_id = doc, load
    if step in ("load", "washing"):
        new_doc, started = _start(doc, pieces, load if step == "washing" else None, now)
        load_id = started.id
    events = [e for p in pieces for e in _events(p, step, now, load_id, place)]
    if step == "ready":
        new_doc = _settle_after(_returned(new_doc, pieces, now), view, pieces, now)
    return Change(
        events=tuple(events),
        laundry=new_doc,
        words=texts.done(step, pieces),
        pieces=tuple(p.id for p in pieces),
        load=load_id,
    )


def _settle_after(
    doc: LaundryDoc, view: WardrobeView, back: Sequence[Piece], now: datetime
) -> LaundryDoc:
    """After a return, the fresh view will show these pieces Ready: settle on that."""
    gone = {p.id for p in back}
    soon = view.model_copy(
        update={
            "pieces": {
                k: (v.model_copy(update={"state": "ready"}) if k in gone else v)
                for k, v in view.pieces.items()
            }
        }
    )
    return settle(doc, soon, now)


__all__ = [
    "IN_LAUNDRY",
    "KEEP",
    "MAX_OPEN",
    "STEPS",
    "WHOLE_LOAD",
    "find",
    "load_of",
    "load_view",
    "new_load_id",
    "open_loads",
    "plan_step",
    "prune",
    "remaining",
    "settle",
    "step_of",
]
