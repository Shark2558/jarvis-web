# src/jarvis/wardrobe/tryon/options.py
"""R13.1 D5, D7 (AVT-06, AVT-09): a slot's readiness and its options, from ONE fresh read.

`Fresh` is one read of the wardrobe view and his plans for the look's day and plan (R13's own
records, read per request: never cached). `readiness(fresh, slot, pieces)` names the slot's
state in fixed words, by R13's engine rules:

- a piece that isn't Ready: its draft words (`model.DRAFT_WORDS`: "Draft: in the laundry" ...);
  a pair with one side not ready: "Draft: one shoe missing"; an In-use piece is fine only as the
  plan's declared shared base (STY-13, as `outfit_plan` itself allows);
- a set part that can't be worn alone without its whole set (STY-16);
- a piece another plan holds against this one (STY-14): "Draft: reserved for your 18:00 event";
- a piece gone (merged away or purged): "Draft: no longer in your wardrobe".

`options(fresh, slot, current, chosen)`: every non-private, non-archived, non-merged piece of the
slot's types (R13's rules), a pair once by its first side, at most 12: the current pick first,
then the ready ones, then the drafts; each with its readiness, its first photo for the thumbnail
and its figure template. A private slot has no options at all (AVT-14).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, tzinfo
from typing import Literal

from jarvis.wardrobe.model import Piece, WardrobeView
from jarvis.wardrobe.styling import reserve, texts
from jarvis.wardrobe.styling.look import sets_of, whole
from jarvis.wardrobe.styling.plans import Plan, StylingDoc
from jarvis.wardrobe.styling.rules import Rules
from jarvis.wardrobe.tryon.assets import effective
from jarvis.wardrobe.tryon.http import LookOption
from jarvis.wardrobe.tryon.model import (
    DRAFT_WORDS,
    ONE_SHOE,
    OPTIONS_MAX,
    PRIVATE_SLOTS,
    READY,
    reserved_words,
)
from jarvis.wardrobe.tryon.store import Asset

GONE = "Draft: no longer in your wardrobe"
SET_WORDS = "Draft: worn only with its set, which isn't ready"
NOT_READY = "Draft: not ready"
PROBE = "op_00000000"  # the day's probe plan when the look is no plan's (as R13's `ask`)
Unit = tuple[str, ...]


@dataclass(frozen=True)
class Fresh:
    view: WardrobeView
    rules: Rules
    zone: tzinfo
    day: date
    code: str
    plan: Plan | None
    held: Mapping[str, Plan]  # piece -> the other plan that holds it against this look


def fresh_of(
    view: WardrobeView, doc: StylingDoc | None, rules: Rules, zone: tzinfo, *, day: date,
    code: str, plan: Plan | None = None,
) -> Fresh:  # fmt: skip
    probe = plan or Plan(id=PROBE, day=day, code=code)
    held = reserve.reserved_for(doc, probe, zone) if doc is not None else {}
    return Fresh(view, rules, zone, day, code, plan, held)


def unit_of(f: Fresh, pids: Sequence[str]) -> Unit:
    """The pieces worn together: the given ones and their pairs, in order, each once."""
    out: list[str] = []
    for pid in pids:
        for i in reserve.unit_of(f.view, pid) if pid in f.view.pieces else (pid,):
            if i not in out:
                out.append(i)
    return tuple(out)


def _handed(f: Fresh, p: Piece) -> bool:
    """In use for the plan this one declared its shared base from, and reusable (STY-13)."""
    plan = f.plan
    if plan is None or plan.shared_from is None or p.id not in plan.shared:
        return False
    return p.state == "in_use" and p.wear == plan.shared_from and f.rules.reusable_piece(p)


def _set_broken(f: Fresh, p: Piece) -> bool:
    return any(not dict(parts).get(p.id, True) and not whole(f.view, parts)
               for _, parts in sets_of(f.view, p.id))  # fmt: skip


Kind = Literal["gone", "one_shoe", "state", "set", "held"]
Block = tuple[Kind, Piece | None]  # why a slot isn't ready, and the piece that makes it so


def blocker(f: Fresh, slot: str, pids: Sequence[str]) -> Block | None:
    """Why the slot can't be worn for this look now, and which piece; None: it can."""
    found = [f.view.pieces.get(i) for i in unit_of(f, pids)]
    pieces = [p for p in found if p is not None and p.merged_into is None]
    if len(pieces) != len(found) or not pieces:
        return "gone", None
    bad = [p for p in pieces if not (p.eligible or _handed(f, p))]
    if bad:
        pair = slot == "shoes" and len(pieces) == 2 and len(bad) == 1
        return ("one_shoe" if pair else "state"), bad[0]
    broken = next((p for p in pieces if _set_broken(f, p)), None)
    if broken is not None:
        return "set", broken
    held = next((p for p in pieces if p.id in f.held), None)
    return ("held", held) if held is not None else None


def readiness(f: Fresh, slot: str, pids: Sequence[str]) -> tuple[str, bool]:
    """(the slot's readiness words, eligible) from this fresh read."""
    block = blocker(f, slot, pids)
    if block is None:
        return READY, True
    kind, p = block
    if kind == "gone" or p is None:
        return GONE, False
    if kind == "one_shoe":
        return ONE_SHOE, False
    if kind == "state":
        return DRAFT_WORDS.get(p.state, NOT_READY), False
    if kind == "set":
        return SET_WORDS, False
    return reserved_words(reserve.held_words(f.held[p.id], f.zone)), False


def unit_words(f: Fresh, unit: Sequence[str]) -> str:
    """ "a charcoal blazer", "a pair of brown dress shoes": fixed words, never his label."""
    return texts.unit_words([f.view.pieces[i] for i in unit if i in f.view.pieces])


def _units(f: Fresh, slot: str) -> list[Unit]:
    seen: set[str] = set()
    out: list[Unit] = []
    for p in sorted(f.view.active(), key=lambda x: x.id):
        if p.private or p.id in seen or f.rules.slot_of(p.type) != slot:
            continue
        unit = (p.id, *(i for i in reserve.unit_of(f.view, p.id) if i != p.id))
        seen.update(unit)
        out.append(unit)
    return out


def _option(f: Fresh, slot: str, unit: Unit, chosen: Mapping[str, Asset]) -> LookOption:
    p = f.view.pieces[unit[0]]
    words, ok = readiness(f, slot, unit)
    template, card = effective(p, chosen)
    return LookOption(
        piece=p.id, words=unit_words(f, unit), readiness=words, eligible=ok,
        photo=p.photos[0] if p.photos else None, template=None if card else template,
    )  # fmt: skip


def options(
    f: Fresh, slot: str, current: Sequence[str], chosen: Mapping[str, Asset]
) -> tuple[LookOption, ...]:
    if slot in PRIVATE_SLOTS:
        return ()
    found = [_option(f, slot, u, chosen) for u in _units(f, slot)]
    now = set(unit_of(f, current))
    first = [x for x in found if x.piece in now]
    rest = sorted((x for x in found if x.piece not in now), key=lambda x: not x.eligible)
    return tuple([*first, *rest][:OPTIONS_MAX])


__all__ = [
    "GONE",
    "Block",
    "Kind",
    "NOT_READY",
    "SET_WORDS",
    "Fresh",
    "blocker",
    "fresh_of",
    "options",
    "readiness",
    "unit_of",
    "unit_words",
]
