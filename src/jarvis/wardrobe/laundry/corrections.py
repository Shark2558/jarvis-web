# src/jarvis/wardrobe/laundry/corrections.py
"""R13 Part B: striking out a laundry step (docs/plans/r13-wardrobe.md D4, LND-05; review M1), pure.

`plan_correct` builds the same `corrected` event A's `correct()` does and, in the SAME commit,
keeps B's own records true to the re-fold:
- a struck-out `load_started` takes the piece out of its load (a load left empty is gone), so a
  load never says Washing while that piece sits in the basket;
- a struck-out `sent_out` takes it off its batch (an empty batch is gone; one with nothing left
  out closes), so no false "overdue" goes out; a struck-out `received` or `returned` puts it back
  on its batch or load (reopened), so no piece is stranded at the shop without a batch (M3);
- a struck-out hold (`held`, `blind`, an unconfirmed change) shrinks the check that holds it, or
  closes it when nothing is left to ask (a pending deposit stays: something still went in).
The card-only kinds (`registered`, `archived`, `restored`, `merged`, `corrected`: A's
`CARD_ONLY`) are undone with their own button, never here (`history.to_correct` refuses them).
"""

from __future__ import annotations

from datetime import datetime

from jarvis.wardrobe.laundry import loads, providers, review, texts
from jarvis.wardrobe.laundry.holds import tap
from jarvis.wardrobe.laundry.store import Batch, Change, Entry, LaundryDoc, Load, ReviewDoc
from jarvis.wardrobe.model import Event, WardrobeView
from jarvis.wardrobe.ports import Refused

CARD_ONLY = frozenset({"registered", "archived", "restored", "merged", "corrected"})


def _drop(items: tuple[str, ...], pid: str) -> tuple[str, ...]:
    return tuple(x for x in items if x != pid)


def _off_load(doc: LaundryDoc, load: Load, pid: str) -> LaundryDoc:
    if pid not in load.pieces or pid in load.back:
        return doc
    left = _drop(load.pieces, pid)
    kept = tuple(x for x in doc.loads if x.id != load.id)
    if left:
        kept += (load.model_copy(update={"pieces": left}),)
    return doc.model_copy(update={"loads": kept})


def _off_batch(doc: LaundryDoc, batch: Batch, pid: str, now: datetime) -> LaundryDoc:
    if pid not in batch.pieces or pid in batch.back:
        return doc
    left = _drop(batch.pieces, pid)
    kept = tuple(b for b in doc.batches if b.id != batch.id)
    if left:
        out = batch.model_copy(update={"pieces": left})
        if not providers.outstanding(out):
            out = out.model_copy(update={"closed_at": now, "short": False})
        kept += (out,)
    return doc.model_copy(update={"batches": kept})


def _back_out(doc: LaundryDoc, pid: str, batch_id: str | None) -> LaundryDoc:
    """A struck-out return: the piece is out again on its batch (or load), reopened."""
    for b in reversed(doc.batches):
        if pid in b.back and (batch_id is None or b.id == batch_id):
            back = _drop(b.back, pid)
            out = b.model_copy(update={"back": back, "closed_at": None, "short": bool(back)})
            return doc.model_copy(
                update={"batches": tuple(out if x.id == b.id else x for x in doc.batches)}
            )
    return doc


def _load_back(doc: LaundryDoc, pid: str) -> LaundryDoc:
    for x in reversed(doc.loads):
        if pid in x.back:
            out = x.model_copy(update={"back": _drop(x.back, pid), "closed_at": None})
            return doc.model_copy(
                update={"loads": tuple(out if y.id == x.id else y for y in doc.loads)}
            )
    return doc


def reconcile_laundry(
    doc: LaundryDoc, view: WardrobeView, target: Event, now: datetime
) -> LaundryDoc:
    pid = target.piece
    if target.kind == "load_started":
        load = next((x for x in loads.open_loads(doc) if x.id == target.load), None)
        return loads.settle(_off_load(doc, load, pid), view, now) if load else doc
    if target.kind == "sent_out":
        batch = next((b for b in providers.open_batches(doc) if b.id == target.batch), None)
        return _off_batch(doc, batch, pid, now) if batch else doc
    if target.kind == "received":
        return _back_out(doc, pid, target.batch)
    if target.kind == "returned":
        return _load_back(doc, pid)
    return doc


def _shrunk(e: Entry, target: Event, now: datetime) -> Entry:
    pid = target.piece
    update: dict[str, object] = {
        "events": _drop(e.events, target.id),
        "pieces": _drop(e.pieces, pid),
    }
    if e.kind == "pending_deposit":  # something still went in: he still says which
        return e.model_copy(update=update)
    update["candidates"] = _drop(e.candidates, pid)
    if not update["pieces"] and not update["candidates"]:
        update["closed_at"] = now
    return e.model_copy(update=update)


def reconcile_review(doc: ReviewDoc, target: Event, now: datetime) -> ReviewDoc:
    out = doc
    for e in review.open_entries(doc):
        if target.id in e.events:
            out = review.put(out, _shrunk(e, target, now))
    return out


def plan_correct(
    view: WardrobeView, laundry: LaundryDoc, queue: ReviewDoc, target: Event, now: datetime
) -> Change:
    if target.piece not in view.pieces:
        raise Refused(texts.UNKNOWN_PIECE)
    if target.kind in CARD_ONLY:
        raise Refused(texts.OWN_BUTTON)
    fix = tap(target.piece, "corrected", now, voids=target.id)
    return Change(
        events=(fix,),
        laundry=reconcile_laundry(laundry, view, target, now),
        review=reconcile_review(queue, target, now),
        words=texts.CORRECTED,
        pieces=(target.piece,),
    )


__all__ = ["CARD_ONLY", "plan_correct", "reconcile_laundry", "reconcile_review"]
