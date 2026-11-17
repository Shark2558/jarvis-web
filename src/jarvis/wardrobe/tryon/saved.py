# src/jarvis/wardrobe/tryon/saved.py
"""R13.1 D7 (AVT-11's half): saved comparisons in `tryon/{uid}.saved`.

At most ten, each one look or two compared: piece ids per slot, tuck, open, layers (never a
picture). Saving checks each look is his (`confirm.units_of`: each piece his, in its own slot, one
a slot or its pair) and keeps no private piece: the figure always wears the base layer there
(AVT-14), so there is nothing of it to keep. Every read re-checks each slot from a FRESH read
(`options.readiness`, against the look's own plan when it still exists, else today's): one word
a slot in its order, and the look is "Draft" while any piece isn't eligible. A piece made private
since is not served. A measurement version never touches any of this (AVT-03).
"""

from __future__ import annotations

from datetime import datetime

from jarvis.wardrobe.model import WardrobeView
from jarvis.wardrobe.tryon import options as o
from jarvis.wardrobe.tryon.confirm import BadSlots, units_of
from jarvis.wardrobe.tryon.http import (
    ConfirmSlot,
    Deleted,
    SavedIn,
    SavedLook,
    SavedLookView,
    SavedRef,
    SavedView,
)
from jarvis.wardrobe.tryon.looks import Read
from jarvis.wardrobe.tryon.model import PRIVATE_SLOTS, SAVED_MAX, new_saved_id
from jarvis.wardrobe.tryon.store import KeptLook, Saved, SlotRec, TryonDoc

GONE = "That comparison isn't there any more."
ALREADY = "Already gone."
DELETED = "Deleted."
FULL_SAVED = f"You keep at most {SAVED_MAX} comparisons: delete one first."
ONLY_PRIVATE = "A comparison needs a piece the figure shows: a private basic is always covered."


class SavedFull(ValueError):
    """Ten are kept already: a 409 in words."""


class SavedGone(LookupError):
    """No saved comparison of his has that id: a 404 in words."""


def hidden(view: WardrobeView, slot: str, pid: str) -> bool:
    """A private slot, or a piece of his that is private: never kept in, or served from, one."""
    p = view.pieces.get(pid)
    return slot in PRIVATE_SLOTS or (p is not None and p.private)


def kept_look(r: Read, look: SavedLook) -> KeptLook:
    shown = [s for s in look.slots if not hidden(r.view, s.slot, s.piece)]
    if not shown:
        raise BadSlots(ONLY_PRIVATE)
    units_of(r.view, r.s.rules, shown)  # each his, in its slot, one a slot (or BadSlots)
    return KeptLook(
        plan=look.plan, slots=tuple(SlotRec(slot=s.slot, piece=s.piece) for s in shown),
        tucked=look.tucked, open=look.open, layers=look.layers,
    )  # fmt: skip


def add(doc: TryonDoc, r: Read, body: SavedIn, at: datetime) -> tuple[TryonDoc, Saved]:
    if len(doc.saved) >= SAVED_MAX:
        raise SavedFull(FULL_SAVED)
    made = Saved(id=new_saved_id(), at=at, looks=tuple(kept_look(r, x) for x in body.looks))
    return doc.model_copy(update={"saved": (*doc.saved, made)}), made


def find(doc: TryonDoc, sid: str) -> Saved:
    found = next((x for x in doc.saved if x.id == sid), None)
    if found is None:
        raise SavedGone(GONE)
    return found


def drop(doc: TryonDoc, sid: str) -> tuple[TryonDoc, bool]:
    left = tuple(x for x in doc.saved if x.id != sid)
    return doc.model_copy(update={"saved": left}), len(left) != len(doc.saved)


def deleted(gone: bool) -> Deleted:
    return Deleted(deleted=gone, message=DELETED if gone else ALREADY)


def _fresh(r: Read, look: KeptLook) -> o.Fresh:
    plan = r.doc.plan(look.plan) if look.plan else None
    if plan is not None and not plan.cancelled:
        return r.fresh(day=plan.day, code=plan.code, plan=plan)
    return r.fresh(day=r.here.today, code=r.s.rules.code_of(None, event=False), plan=None)


def look_view(r: Read, look: KeptLook) -> SavedLookView | None:
    """The look as kept, re-checked now; None when nothing of it may be shown any more."""
    f = _fresh(r, look)
    slots = [s for s in look.slots if not hidden(r.view, s.slot, s.piece)]
    if not slots:
        return None
    words = [o.readiness(f, s.slot, (s.piece,)) for s in slots]
    shown = SavedLook(
        plan=look.plan, slots=tuple(ConfirmSlot(slot=s.slot, piece=s.piece) for s in slots),
        tucked=look.tucked, open=look.open, layers=look.layers,
    )  # fmt: skip
    return SavedLookView(
        look=shown, readiness=tuple(w for w, _ in words), draft=not all(ok for _, ok in words)
    )


def saved_view(r: Read, saved: Saved) -> SavedView:
    looks = tuple(v for v in (look_view(r, x) for x in saved.looks) if v is not None)
    draft = len(looks) < len(saved.looks) or any(v.draft for v in looks)
    return SavedView(id=saved.id, at=saved.at, looks=looks, draft=draft)


def ref_of(r: Read | None, saved: Saved) -> SavedRef:
    """For GET /v1/tryon: Draft when it can't be checked now (R13 off), never a guess of Ready."""
    draft = True if r is None else saved_view(r, saved).draft
    return SavedRef(id=saved.id, at=saved.at, draft=draft)


__all__ = [
    "ALREADY",
    "DELETED",
    "FULL_SAVED",
    "GONE",
    "ONLY_PRIVATE",
    "SavedFull",
    "SavedGone",
    "add",
    "deleted",
    "drop",
    "find",
    "hidden",
    "kept_look",
    "look_view",
    "ref_of",
    "saved_view",
]
