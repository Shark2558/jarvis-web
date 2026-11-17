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
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any, TypeVar

from jarvis.wardrobe.model import Piece, WardrobeView
from jarvis.wardrobe.styling import reserve, texts
from jarvis.wardrobe.styling.actions import NOT_READY
from jarvis.wardrobe.styling.rules import Rules
from jarvis.wardrobe.tryon import options as o
from jarvis.wardrobe.tryon.http import ConfirmIn, ConfirmSlot
from jarvis.wardrobe.tryon.looks import GONE_PLAN, NOT_HIS, TWO, WRONG_SLOT, Looks, NoLook

CANT = "it can't be confirmed for this event."
R = TypeVar("R")
Units = list[tuple[str, tuple[str, ...]]]


class Draft(ValueError):
    """A piece of the look isn't eligible now: a 409 in words; no tool call was made."""


class BadSlots(ValueError):
    """The slots are not a look of his (a stranger, a piece in another's slot, two in one)."""


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


def _the(p: Piece) -> str:
    words = texts.piece_words(p)
    return "The " + (words[2:] if words.startswith("a ") else words)


def words_of(f: o.Fresh, block: o.Block) -> str:
    """ "The navy jacket is in the laundry: it can't be confirmed for this event." """
    kind, p = block
    if p is None:
        return NOT_HIS
    verb = "are" if p.type in texts.PLURAL_TYPES and not p.private else "is"
    if kind in ("state", "one_shoe"):
        state = NOT_READY.get(p.state, "{is} not ready").replace("{is}", verb)
    elif kind == "set":
        state = f"{verb} worn only with its set, which isn't ready"
    else:
        state = f"{verb} reserved for {reserve.held_words(f.held[p.id], f.zone)}"
    return f"{_the(p)} {state}: {CANT}"


def first_draft(f: o.Fresh, units: Units) -> str | None:
    """The refusal's words for the first slot that can't be worn now, else None."""
    for slot, unit in units:
        block = o.blocker(f, slot, unit)
        if block is not None:
            return words_of(f, block)
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
    return await call({"action": "lock", "plan": plan.id, "pieces": [u[0] for _, u in units]})


__all__ = ["CANT", "BadSlots", "Draft", "check_and_lock", "first_draft", "units_of", "words_of"]
