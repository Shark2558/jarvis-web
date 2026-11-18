# src/jarvis/wardrobe/tryon/confirm.py
"""R13.1 D7, D20 (AVT-09): "Use this look for the plan".

`check_and_lock(looks, uid, body, call)`: the plan must be there; the slots must be a look (each
piece his, in its own slot, one a slot or its pair); then EVERY piece is re-checked from a FRESH
read of the view and his plans (`options.blocker`: by R13's engine rules) BEFORE any tool call,
and a draft is refused in plain words ("The navy jacket is in the laundry: it can't be confirmed
for this event."). When all are eligible it makes ONE call, `call({"action": "lock", "plan": ...,
"pieces": [one a slot]})`: the route passes R13's shared `api.wardrobe.run_panel_tool`, so the
cards, rows and audit are R13's and one press makes at most one card. The early check is for the
words; `outfit_plan`'s own check is the guarantee (D20: a piece that goes to the laundry between
the two is refused there, the plan unchanged).

D7's **Remove** (outer, belt, watch, socks) can't be kept by a plan: R13's engine fills every slot
of the dress code again on each read (a pick dropped from the plan, or R13's own `release` of
it, comes back as the same piece). So a look that leaves out a removable slot the plan's fresh
look holds is refused in words before any call ("This plan can't leave out its watch yet: ..."),
and the screen never says "used" while the plan keeps a watch (review A-1 F2). A covered slot
(a private piece: no id to send) is never asked for.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any, TypeVar

from jarvis.wardrobe.model import WardrobeView
from jarvis.wardrobe.styling import ready, reserve
from jarvis.wardrobe.styling.look import Pick
from jarvis.wardrobe.styling.rules import Rules
from jarvis.wardrobe.tryon import options as o
from jarvis.wardrobe.tryon.http import ConfirmIn, ConfirmSlot
from jarvis.wardrobe.tryon.looks import (
    GONE_PLAN,
    NOT_HIS,
    TWO,
    WRONG_SLOT,
    Looks,
    NoLook,
    covered,
)
from jarvis.wardrobe.tryon.model import REMOVABLE_SLOTS

CANT = "it can't be confirmed for this event."
LEFT_OUT = (
    "This plan can't leave out its {w} yet: put the {w} back on the figure to use this look for it."
)
R = TypeVar("R")
Units = list[tuple[str, tuple[str, ...]]]


class Draft(ValueError):
    """A piece of the look isn't eligible now: a 409 in words; no tool call was made."""


class BadSlots(ValueError):
    """The slots are not a look of his (a stranger, a piece in another's slot, two in one)."""


class LeftOut(ValueError):
    """The look leaves out a removable slot the plan's look holds: a 409 in words, no call."""


def units_of(view: WardrobeView, rules: Rules, slots: Sequence[ConfirmSlot]) -> Units:
    """[(slot, its pieces)] in his order: each his, in its own slot, one a slot or its pair."""
    by: dict[str, list[str]] = {}
    for s in slots:
        p = view.pieces.get(s.piece)
        if p is None or p.merged_into is not None:
            raise BadSlots(NOT_HIS)
        if rules.slot_of(p.type) != s.slot:
            raise BadSlots(WRONG_SLOT)
        ids = by.setdefault(s.slot, [])
        if ids and s.piece not in reserve.unit_of(view, ids[0]):
            raise BadSlots(TWO)
        if s.piece not in ids:
            ids.append(s.piece)
    return [(slot, tuple(ids)) for slot, ids in by.items()]


def words_of(f: o.Fresh, block: o.Block) -> str:
    """ "The navy jacket is in the laundry: it can't be confirmed for this event." (R13's own
    words for each state, `styling.ready`: review I1 M5)"""
    kind, p = block
    if p is None:
        return NOT_HIS
    if kind in ("state", "one_shoe"):
        state = ready.state_words(p)
    elif kind == "set":
        state = f"{ready.verb(p)} worn only with its set, which isn't ready"
    else:
        state = f"{ready.verb(p)} reserved for {reserve.held_words(f.held[p.id], f.zone)}"
    return f"{ready.the(p)} {state}: {CANT}"


def first_draft(f: o.Fresh, units: Units) -> str | None:
    """The refusal's words for the first slot that can't be worn now, else None."""
    for slot, unit in units:
        block = o.blocker(f, slot, unit)
        if block is not None:
            return words_of(f, block)
    return None


def left_out(view: WardrobeView, rules: Rules, held: Sequence[Pick], units: Units) -> str | None:
    """The words for the first removable slot the plan's look `held` holds and the look leaves
    out (never a covered one: he has no id to send), else None."""
    sent = {slot for slot, _ in units}
    for pick in held:
        slot = pick.slot
        if slot in REMOVABLE_SLOTS and slot not in sent and not covered(view, slot, pick.pieces):
            return LEFT_OUT.format(w=rules.slot_words_of(slot))
    return None


async def check_and_lock(
    looks: Looks, uid: str, body: ConfirmIn, call: Callable[[dict[str, Any]], Awaitable[R]]
) -> R:
    r = await looks.read(uid)
    plan = r.doc.plan(body.plan)
    if plan is None or plan.cancelled:
        raise NoLook(GONE_PLAN)
    units = units_of(r.view, r.s.rules, body.slots)
    words = first_draft(r.fresh(day=plan.day, code=plan.code, plan=plan), units)
    if words is not None:
        raise Draft(words)  # before any tool call (D7)
    now = await r.s.answer(uid, r.here, r.doc, r.view, plan)  # the plan's look, as it reads now
    gap = left_out(r.view, r.s.rules, now.suggestion.primary.picks, units)
    if gap is not None:
        raise LeftOut(gap)  # D7's Remove: before any tool call (review A-1 F2)
    return await call({"action": "lock", "plan": plan.id, "pieces": [u[0] for _, u in units]})


__all__ = [
    "CANT",
    "LEFT_OUT",
    "BadSlots",
    "Draft",
    "LeftOut",
    "check_and_lock",
    "first_draft",
    "left_out",
    "units_of",
    "words_of",
]
