# src/jarvis/wardrobe/styling/engine.py
"""R13 D12 (docs/plans/r13-wardrobe.md): the outfit engine. Pure: a view, an `Ask`, the rules.

For each slot of the dress code (`FILL_ORDER`), the pieces of its types go through the hard
exclusions in order (`STEPS`): formality, "okay to stain" (Holi, never a delicate piece), his
"never" rules and exclusions, rain-ok outdoors, availability (Ready; In use only through a
declared hand-off of a reusable piece, D3; a pair only whole; a set part that can't be worn alone
only with its whole set, festive) and reservations by another plan. The first step that leaves
a required slot empty is named in its gap, with a next action (`rank.gap`). What is left is
ranked (`rank.best`), ties broken by piece id. His locks are kept while available; a plan's own
picks while they still fit. A primary look and up to two alternatives (another top, else bottom,
else shoes), each with reasons naming the actual piece ids (STY-11); a piece due back from the
laundry shop by the day is an outstanding action (LND-16).

`AVAILABILITY` is read at call time: only the eval's negative control turns it off.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace

from jarvis.wardrobe.model import Piece, WardrobeView
from jarvis.wardrobe.states import STATE_WORDS
from jarvis.wardrobe.styling import rank, texts
from jarvis.wardrobe.styling.look import (
    FILL_ORDER,
    FORMAL_SLOTS,
    PRIVATE_SLOTS,
    Ask,
    LookOut,
    Pick,
    Run,
    Suggestion,
    Unit,
    never_hit,
    sets_of,
    whole,
)
from jarvis.wardrobe.styling.rules import Rules

AVAILABILITY = True  # the eval's control turns it off; nothing else may
VARY = ("top", "bottom", "shoes")
MAX_ALTERNATIVES = 2


# ---- the hard exclusions, in order -------------------------------------------------------------
def _handed(r: Run, p: Piece) -> bool:
    """In use, worn for the very plan this one declared its shared base from, and reusable."""
    return (
        p.state == "in_use"
        and p.wear is not None
        and r.ask.shared.get(p.id) == p.wear
        and r.rules.reusable_piece(p)
    )


def available(r: Run, p: Piece) -> bool:
    if not AVAILABILITY:
        return True
    if not (p.eligible or _handed(r, p)):
        return False
    for _, parts in sets_of(r.view, p.id):
        if dict(parts).get(p.id, True):
            continue  # it can be worn alone
        if not (r.code.sets_whole and whole(r.view, parts)):
            return False  # it needs its whole set, and a dress code that wears sets whole
        for mate, _alone in parts:
            slot = r.rules.slot_of(r.p(mate).type) if mate in r.view.pieces else None
            taken = r.picks.get(slot or "")
            if mate != p.id and taken is not None and mate not in taken.pieces:
                return False
    return True


def _formal_ok(r: Run, slot: str, p: Piece) -> bool:
    return slot not in FORMAL_SLOTS or r.rules.formality_of(p) >= r.code.min


def _mess_ok(r: Run, slot: str, p: Piece) -> bool:
    return slot in PRIVATE_SLOTS or not r.code.mess_ok or (p.mess_ok and not p.delicate)


def _prefs_ok(r: Run, slot: str, p: Piece) -> bool:
    return p.id not in r.ask.excluded and never_hit(r, p) is None


def _weather_ok(r: Run, slot: str, p: Piece) -> bool:
    needs = bool(r.ask.rain and r.ask.outdoor) and slot in ("shoes", "outer")
    return not needs or "rain_ok" in p.weather


Step = tuple[str, Callable[[Run, str, Piece], bool]]
STEPS: tuple[Step, ...] = (
    ("formality", _formal_ok),
    ("mess", _mess_ok),
    ("prefs", _prefs_ok),
    ("weather", _weather_ok),
    ("available", lambda r, s, p: available(r, p)),
    ("reserved", lambda r, s, p: p.id not in r.ask.reserved),
)


def _units(r: Run, slot: str) -> list[Unit]:
    types = r.rules.types_for(r.ask.code, slot)
    if slot not in r.rules.paired:
        return sorted((p.id,) for p in r.view.active() if p.type in types)
    pairs = [tuple(x.pieces) for x in r.view.pairs.values()]
    found = [u for u in pairs if all(i in r.view.pieces for i in u)]
    return sorted(u for u in found if all(r.p(i).type in types for i in u))


def _filter(r: Run, slot: str, units: list[Unit]) -> tuple[list[Unit], str | None, list[Unit]]:
    """(what passes every step, the first step that emptied it, what that step removed)."""
    if not units:
        return [], None, []
    for name, ok in STEPS:
        kept = [u for u in units if all(ok(r, slot, r.p(i)) for i in u)]
        if not kept:
            return [], name, units
        units = kept
    return units, None, []


# ---- filling -------------------------------------------------------------------------------------
def _slots(r: Run) -> list[tuple[str, bool]]:
    wanted = dict.fromkeys(r.code.required, True)
    for s in r.code.optional:
        wanted.setdefault(s, False)
    if r.ask.rain:
        wanted["outer"] = bool(r.ask.outdoor) or wanted.get("outer", False)
    elif wanted.get("outer") is False and (r.ask.hot or not (r.ask.cold or r.code.target >= 4)):
        del wanted["outer"]
    return [(s, wanted[s]) for s in FILL_ORDER if s in wanted]


def _take(r: Run, slot: str, unit: Unit, *, locked: bool) -> None:
    r.picks[slot] = Pick(slot, unit, locked)
    r.reasons.append(rank.why(r, slot, unit))
    for pid in unit:
        _place_mates(r, pid)
        if (line := rank.stale(r, r.p(pid))) is not None:
            r.compromises.append(line)


def _place_mates(r: Run, pid: str) -> None:
    for sid, parts in sets_of(r.view, pid):
        mates = [x for x, _ in parts if x != pid and x in r.view.pieces]
        if not whole(r.view, parts):
            out = [r.p(x) for x in mates if not r.p(x).eligible]
            if out and r.code.sets_whole:
                lines = texts.states_line(out)
                r.compromises.append(
                    f"The set {sid} can't be worn whole: {lines}; {pid} can be worn alone."
                )
            continue
        if not (r.code.sets_whole or not dict(parts).get(pid, True)):
            continue
        for x in mates:
            slot = r.rules.slot_of(r.p(x).type)
            if slot is not None and slot not in r.picks:
                r.picks[slot] = Pick(slot, (x,))
                r.reasons.append(rank.why(r, slot, (x,)))
        ids = texts.ids_words([x for x, _ in parts])
        r.reasons.append(f"The set {sid} is complete: {ids} are ready.")


def _why_not(r: Run, unit: Unit) -> str:
    held = [r.ask.reserved[i] for i in unit if i in r.ask.reserved]
    if held and all(available(r, r.p(i)) for i in unit):
        return f"reserved for {held[0]}"
    return ", ".join(sorted({STATE_WORDS[r.p(i).state] for i in unit}))


def _kept(r: Run, slot: str, units: list[Unit], *, locked: bool) -> bool:
    """His lock (kept while available) or the plan's pick (kept while it still fits)."""
    unit = (r.ask.locked if locked else r.ask.keep).get(slot)
    if not unit or set(unit) & r.ask.skip.get(slot, frozenset()):
        return False
    if any(i not in r.view.pieces for i in unit):
        return False
    usable = all(available(r, r.p(i)) and i not in r.ask.reserved for i in unit)
    if (locked and usable) or unit in units:
        _take(r, slot, unit, locked=locked)
        return True
    if locked or not usable:
        what = f"{r.words(unit)} ({texts.ids_words(unit)})"
        why = _why_not(r, unit)
        r.compromises.append(f"{what[0].upper()}{what[1:]} is {why}: another one is suggested.")
    return False


def _fill_slot(r: Run, slot: str, required: bool, ban: frozenset[str]) -> None:
    units, step, removed = _filter(r, slot, _units(r, slot))
    if _kept(r, slot, units, locked=True) or _kept(r, slot, units, locked=False):
        return
    skip = r.ask.skip.get(slot, frozenset()) | ban
    left = [u for u in units if not set(u) & skip]
    if units and not left and not ban:
        words = r.rules.slot_words_of(slot)
        r.compromises.append(f"No other {words} fits: {texts.ids_words(units[0])} stay.")
        left = units[:1]
    if left:
        _take(r, slot, rank.best(r, slot, left), locked=False)
    elif required:
        r.gaps.append(rank.gap(r, slot, step, removed))


def _outstanding(r: Run) -> None:
    """LND-16: a piece due back from the laundry shop by the plan's day is an outstanding action."""
    for slot, _ in _slots(r):
        types = r.rules.types_for(r.ask.code, slot)
        for p in sorted(r.view.active(), key=lambda x: x.id):
            due = p.expected_back
            if p.type not in types or p.state != "with_provider" or due is None:
                continue
            if due <= r.ask.day:
                r.gaps.append(
                    f"Outstanding: collect {texts.piece_words(p)} ({p.id}) from the laundry "
                    f"shop, due back {texts.date_words(due)}."
                )


def _look(view: WardrobeView, ask: Ask, rules: Rules, ban: Mapping[str, frozenset[str]]) -> LookOut:
    r = Run(view, ask, rules)
    r.reasons.append(rank.header(r))
    for slot, required in _slots(r):
        if slot not in r.picks:
            _fill_slot(r, slot, required, ban.get(slot, frozenset()))
    _outstanding(r)
    order = {s: n for n, s in enumerate(FILL_ORDER)}
    picks = tuple(sorted(r.picks.values(), key=lambda p: order.get(p.slot, len(order))))
    return LookOut(picks, tuple(r.reasons), tuple(dict.fromkeys(r.compromises)), tuple(r.gaps))


def _alternatives(
    view: WardrobeView, ask: Ask, rules: Rules, primary: LookOut
) -> tuple[LookOut, ...]:
    looks, ban = [primary], dict[str, frozenset[str]]()
    for _ in range(MAX_ALTERNATIVES):
        found = None
        for slot in VARY:
            got = looks[-1].pick(slot)
            if slot in ask.locked or got is None:
                continue
            trial = {**ban, slot: ban.get(slot, frozenset()) | set(got.pieces)}
            alt = _look(view, ask, rules, trial)
            if alt.pick(slot) is not None and len(alt.gaps) <= len(primary.gaps):
                found, ban = alt, trial
                break
        if found is None or any(found.picks == x.picks for x in looks):
            break
        looks.append(found)
    return tuple(looks[1:])


def suggest(view: WardrobeView, ask: Ask, rules: Rules) -> Suggestion:
    primary = _look(view, ask, rules, {})
    return Suggestion(primary, _alternatives(view, ask, rules, primary))


def fill_one(
    view: WardrobeView, ask: Ask, rules: Rules, slot: str, keep: Iterable[Pick]
) -> Pick | None:
    """A ready substitute for one slot, every other pick kept (C's refresh, STY-15)."""
    locked = {p.slot: p.pieces for p in keep if p.slot != slot}
    return _look(view, replace(ask, locked=locked, keep={}), rules, {}).pick(slot)


__all__ = [
    "AVAILABILITY",
    "FILL_ORDER",
    "STEPS",
    "Ask",
    "LookOut",
    "Pick",
    "Suggestion",
    "available",
    "fill_one",
    "suggest",
]
