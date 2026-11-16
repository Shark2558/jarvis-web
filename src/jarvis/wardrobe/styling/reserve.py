# src/jarvis/wardrobe/styling/reserve.py
"""R13 D12, STY-13, STY-14 (docs/plans/r13-wardrobe.md): a plan's picks are its reservations.

- `window(plan)`: its event's start and end, else his whole local day.
- A plan holds its pieces against another plan of the SAME local day (a shirt worn at 10:00 is
  not clean at 19:00; a pair of trousers is In use until it is back, D3) or with an overlapping
  window. Not a cancelled plan, nor a worn one (what it holds is now In use, and the states say
  the rest), and never a piece the two plans declared shared (`reserved_for`).
- `transfer`: a deliberate move of a piece (or its pair) from one plan to another; the plan it
  leaves needs a new one for that slot.
- `share`: a later plan the same day declares a shared base from an earlier one (STY-13): only
  pieces the earlier plan holds and the rewear rule wears again (`Rules.reusable_piece`); they
  join the later plan's picks, locked. Pure: plans in, plans out; `PlanRefused` in plain words.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, time, timedelta, tzinfo

from jarvis.wardrobe.model import WardrobeView
from jarvis.wardrobe.styling import texts
from jarvis.wardrobe.styling.plans import Plan, PlanPick, PlanRefused, StylingDoc
from jarvis.wardrobe.styling.rules import Rules


def window(plan: Plan, zone: tzinfo) -> tuple[datetime, datetime]:
    if plan.starts is not None and plan.ends is not None:
        return plan.starts, plan.ends
    start = datetime.combine(plan.day, time.min, tzinfo=zone)
    return start, start + timedelta(days=1)


def holds_against(a: Plan, b: Plan, zone: tzinfo) -> bool:
    """Do `a`'s picks hold against `b`?"""
    if a.id == b.id or a.cancelled or a.worn:
        return False
    if a.day == b.day:
        return True
    (s1, e1), (s2, e2) = window(a, zone), window(b, zone)
    return s1 < e2 and s2 < e1


def _shared(a: Plan, b: Plan) -> set[str]:
    out: set[str] = set()
    if b.shared_from == a.id:
        out |= set(b.shared)
    if a.shared_from == b.id:
        out |= set(a.shared)
    return out


def reserved_for(doc: StylingDoc, plan: Plan, zone: tzinfo) -> dict[str, Plan]:
    """Every piece another plan holds against `plan`, with that plan."""
    out: dict[str, Plan] = {}
    for other in doc.plans:
        if not holds_against(other, plan, zone):
            continue
        shared = _shared(other, plan)
        for pid in other.pieces():
            if pid not in shared:
                out.setdefault(pid, other)
    return out


def held_words(other: Plan, zone: tzinfo) -> str:
    return texts.event_words(other.starts, zone)


def unit_of(view: WardrobeView, pid: str) -> tuple[str, ...]:
    """A piece, or its pair (both sides are worn together)."""
    pair = next((p for p in view.pairs.values() if pid in p.pieces), None)
    return tuple(pair.pieces) if pair is not None else (pid,)


def with_pick(plan: Plan, pick: PlanPick) -> Plan:
    clash = set(pick.pieces)
    picks = tuple(p for p in plan.picks if p.slot != pick.slot and not set(p.pieces) & clash)
    needs = tuple(n for n in plan.needs if n != pick.slot)
    return plan.model_copy(update={"picks": (*picks, pick), "needs": needs})


def without(plan: Plan, pieces: Sequence[str]) -> tuple[Plan, str | None]:
    """`plan` without the pick holding any of `pieces`, and that pick's slot."""
    gone = next((p for p in plan.picks if set(p.pieces) & set(pieces)), None)
    if gone is None:
        return plan, None
    picks = tuple(p for p in plan.picks if p is not gone)
    return plan.model_copy(update={"picks": picks}), gone.slot


def conflict(doc: StylingDoc, plan: Plan, unit: Sequence[str], zone: tzinfo) -> str | None:
    """The words of a refusal when another plan holds a piece of `unit` against `plan`."""
    held = reserved_for(doc, plan, zone)
    for pid in unit:
        if pid in held:
            words = held_words(held[pid], zone)
            return f"{pid} is reserved for {words}: transfer it, or pick another."
    return None


def transfer(
    doc: StylingDoc, to: Plan, source: Plan, pid: str, view: WardrobeView, rules: Rules
) -> StylingDoc:
    if source.pick_of(pid) is None:
        raise PlanRefused(f"{pid} isn't in that plan.")
    if pid not in view.pieces:  # purged since it was planned (security review L8)
        raise PlanRefused("That piece isn't in your wardrobe any more.")
    unit = unit_of(view, pid)
    slot = rules.slot_of(view.pieces[pid].type)
    if slot is None:
        raise PlanRefused(f"{pid} doesn't go in an outfit.")
    left, gone = without(source, unit)
    left = left.model_copy(update={"needs": tuple(dict.fromkeys((*left.needs, gone or slot)))})
    moved = with_pick(to, PlanPick(slot=slot, pieces=unit, locked=True))
    return doc.put(left).put(moved)


def can_share_from(source: Plan, plan: Plan) -> bool:
    """Can `plan` declare a shared base from `source`: an earlier plan of the same day?"""
    if source.day != plan.day or source.id == plan.id:
        return False
    return not (source.starts and plan.starts and source.starts >= plan.starts)


def share(
    doc: StylingDoc,
    plan: Plan,
    source: Plan,
    pieces: Sequence[str],
    view: WardrobeView,
    rules: Rules,
) -> StylingDoc:
    if not can_share_from(source, plan):
        raise PlanRefused("A shared base comes from an earlier plan the same day.")
    units: list[tuple[str, tuple[str, ...]]] = []
    for pid in pieces:
        p = view.pieces.get(pid)
        if p is None or source.pick_of(pid) is None:
            raise PlanRefused(f"{pid} isn't in that plan.")
        if not rules.reusable_piece(p):
            words = texts.piece_words(p)
            raise PlanRefused(
                f"{words[0].upper()}{words[1:]} goes to the laundry after a wear: it can't be "
                "shared with this plan."
            )
        slot = rules.slot_of(p.type)
        if slot is not None:
            units.append((slot, unit_of(view, pid)))
    shared = tuple(dict.fromkeys(i for _, u in units for i in u))
    new = plan.model_copy(update={"shared_from": source.id, "shared": shared})
    for slot, unit in units:
        new = with_pick(new, PlanPick(slot=slot, pieces=unit, locked=True))
    return doc.put(new)


__all__ = [
    "can_share_from",
    "conflict",
    "held_words",
    "holds_against",
    "reserved_for",
    "share",
    "transfer",
    "unit_of",
    "window",
    "with_pick",
    "without",
]
