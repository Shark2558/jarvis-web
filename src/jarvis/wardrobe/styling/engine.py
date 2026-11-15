# src/jarvis/wardrobe/styling/engine.py
"""R13 D12 (docs/plans/r13-wardrobe.md): the outfit engine. Pure: a view, an `Ask`, the rules.

For each slot of the dress code (`FILL_ORDER`), the pieces of its types go through the hard
exclusions in order (`STEPS`): formality, "okay to stain" (Holi, never a delicate piece), his
"never" rules and exclusions, rain-ok outdoors, availability (Ready; In use only through a
declared hand-off of a reusable piece, D3; a pair only whole; a set part that can't be worn alone
only with its whole set, festive) and reservations by another plan. The first step that leaves
a required slot empty is named in its gap, with a next action. What is left is ranked
(formality, his festive pieces, rain-ok, light fabrics, his colours, colour pairing, a belt that
matches the shoes, recent wear), ties broken by piece id. His locks are kept while available; a
plan's own picks while they still fit. A primary look and up to two alternatives (another top,
else bottom, else shoes), each with reasons naming the actual piece ids (STY-11).

`AVAILABILITY` is read at call time: only the eval's negative control turns it off.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta

from jarvis.wardrobe.model import Piece, WardrobeView
from jarvis.wardrobe.states import STATE_WORDS, wearable_set
from jarvis.wardrobe.styling import texts
from jarvis.wardrobe.styling.rules import CodeRule, Rules

AVAILABILITY = True  # the eval's control turns it off; nothing else may
Unit = tuple[str, ...]
Parts = tuple[tuple[str, bool], ...]
FILL_ORDER = (
    *("top", "bottom", "shoes", "socks", "belt", "watch"),
    *("outer", "base", "underwear", "tie", "cap", "scarf"),
)
FORMAL_SLOTS = frozenset({"top", "bottom", "shoes", "outer"})
PRIVATE_SLOTS = frozenset({"base", "underwear"})
PARTNER = {"bottom": "top", "outer": "top", "socks": "bottom", "belt": "shoes"}
VARY = ("top", "bottom", "shoes")
MAX_ALTERNATIVES = 2


@dataclass(frozen=True)
class Ask:
    day: date
    code: str
    occasion: str | None = None
    rain: bool | None = None
    hot: bool = False
    cold: bool = False
    outdoor: bool | None = None
    locked: Mapping[str, Unit] = field(default_factory=dict)  # his locks: kept while available
    keep: Mapping[str, Unit] = field(default_factory=dict)  # a plan's picks: kept while they fit
    skip: Mapping[str, frozenset[str]] = field(default_factory=dict)  # "change this one"
    shared: Mapping[str, str] = field(default_factory=dict)  # piece -> the plan it is worn for
    reserved: Mapping[str, str] = field(default_factory=dict)  # piece -> "your 10:00 event"
    never: tuple[tuple[str, str], ...] = ()
    excluded: frozenset[str] = frozenset()
    likes: frozenset[str] = frozenset()
    avoids: frozenset[str] = frozenset()
    stale_before: datetime | None = None
    for_words: str = ""  # "your 10:00 event"


@dataclass(frozen=True)
class Pick:
    slot: str
    pieces: Unit
    locked: bool = False


@dataclass(frozen=True)
class LookOut:
    picks: tuple[Pick, ...]
    reasons: tuple[str, ...] = ()
    compromises: tuple[str, ...] = ()
    gaps: tuple[str, ...] = ()

    def pick(self, slot: str) -> Pick | None:
        return next((p for p in self.picks if p.slot == slot), None)

    def ids(self) -> tuple[str, ...]:
        return tuple(pid for p in self.picks for pid in p.pieces)


@dataclass(frozen=True)
class Suggestion:
    primary: LookOut
    alternatives: tuple[LookOut, ...] = ()


@dataclass
class _Run:
    view: WardrobeView
    ask: Ask
    rules: Rules
    picks: dict[str, Pick] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    compromises: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    @property
    def code(self) -> CodeRule:
        return self.rules.codes[self.ask.code]

    def p(self, pid: str) -> Piece:
        return self.view.pieces[pid]

    def words(self, unit: Sequence[str]) -> str:
        return texts.unit_words([self.p(i) for i in unit])


# ---- the hard exclusions, in order -------------------------------------------------------------
def _sets_of(view: WardrobeView, pid: str) -> list[tuple[str, Parts]]:
    return [
        (s.id, tuple((x.piece, x.alone) for x in s.parts))
        for s in view.sets.values()
        if any(x.piece == pid for x in s.parts)
    ]


def _whole(view: WardrobeView, parts: Parts) -> bool:
    states = [(view.pieces[x].state if x in view.pieces else None, a) for x, a in parts]
    return wearable_set(states)[0]


def _handed(r: _Run, p: Piece) -> bool:
    """In use, worn for the very plan this one declared its shared base from, and reusable."""
    return (
        p.state == "in_use"
        and p.wear is not None
        and r.ask.shared.get(p.id) == p.wear
        and r.rules.reusable_piece(p)
    )


def available(r: _Run, p: Piece) -> bool:
    if not AVAILABILITY:
        return True
    if not (p.eligible or _handed(r, p)):
        return False
    for _, parts in _sets_of(r.view, p.id):
        if dict(parts).get(p.id, True):
            continue  # it can be worn alone
        if not (r.code.sets_whole and _whole(r.view, parts)):
            return False  # it needs its whole set, and a dress code that wears sets whole
        for mate, _alone in parts:
            slot = r.rules.slot_of(r.p(mate).type) if mate in r.view.pieces else None
            taken = r.picks.get(slot or "")
            if mate != p.id and taken is not None and mate not in taken.pieces:
                return False
    return True


def _never_hit(r: _Run, p: Piece) -> tuple[str, str] | None:
    own = {"colour": p.colour, "pattern": p.pattern, "type": p.type}
    for feature, value in r.ask.never:
        got = own[feature] if feature in own else p.features.get(feature)
        if got == value:
            return feature, value
    return None


def _formal_ok(r: _Run, slot: str, p: Piece) -> bool:
    return slot not in FORMAL_SLOTS or r.rules.formality_of(p) >= r.code.min


def _mess_ok(r: _Run, slot: str, p: Piece) -> bool:
    return slot in PRIVATE_SLOTS or not r.code.mess_ok or (p.mess_ok and not p.delicate)


def _prefs_ok(r: _Run, slot: str, p: Piece) -> bool:
    return p.id not in r.ask.excluded and _never_hit(r, p) is None


def _weather_ok(r: _Run, slot: str, p: Piece) -> bool:
    needs = bool(r.ask.rain and r.ask.outdoor) and slot in ("shoes", "outer")
    return not needs or "rain_ok" in p.weather


Step = tuple[str, Callable[[_Run, str, Piece], bool]]
STEPS: tuple[Step, ...] = (
    ("formality", _formal_ok),
    ("mess", _mess_ok),
    ("prefs", _prefs_ok),
    ("weather", _weather_ok),
    ("available", lambda r, s, p: available(r, p)),
    ("reserved", lambda r, s, p: p.id not in r.ask.reserved),
)


def _units(r: _Run, slot: str) -> list[Unit]:
    types = r.rules.types_for(r.ask.code, slot)
    if slot not in r.rules.paired:
        return sorted((p.id,) for p in r.view.active() if p.type in types)
    pairs = [tuple(x.pieces) for x in r.view.pairs.values()]
    whole = [u for u in pairs if all(i in r.view.pieces for i in u)]
    return sorted(u for u in whole if all(r.p(i).type in types for i in u))


def _filter(r: _Run, slot: str, units: list[Unit]) -> tuple[list[Unit], str | None, list[Unit]]:
    """(what passes every step, the first step that emptied it, what that step removed)."""
    if not units:
        return [], None, []
    for name, ok in STEPS:
        kept = [u for u in units if all(ok(r, slot, r.p(i)) for i in u)]
        if not kept:
            return [], name, units
        units = kept
    return units, None, []


# ---- ranking -------------------------------------------------------------------------------------
def _recent(r: _Run, p: Piece) -> bool:
    if p.last_worn is None:
        return False
    return r.ask.day - p.last_worn.date() <= timedelta(days=r.rules.recent_days)


def _piece_score(r: _Run, slot: str, p: Piece) -> float:
    s = 0.0
    if slot in FORMAL_SLOTS:
        s -= abs(r.code.target - r.rules.formality_of(p))
    if r.code.occasion and r.code.occasion in p.occasions:
        s += 2
    if r.ask.rain and slot in ("shoes", "outer") and "rain_ok" in p.weather:
        s += 3
    light = any(f.ok and f.v in r.rules.light_fabrics for f in p.fabric)
    s += 1 if r.ask.hot and slot in ("top", "bottom") and light else 0
    s += 1 if p.colour in r.ask.likes else 0
    s -= 2 if p.colour in r.ask.avoids else 0
    s -= 1 if _recent(r, p) else 0
    return s


def _colour(r: _Run, slot: str) -> str | None:
    got = r.picks.get(slot)
    return r.p(got.pieces[0]).colour if got is not None else None


def _match_score(r: _Run, slot: str, p: Piece) -> float:
    partner = _colour(r, PARTNER[slot]) if slot in PARTNER else None
    s = 0.0
    if slot in ("bottom", "outer", "socks"):
        s += r.rules.pairs_with(p.colour, partner)
    if slot == "socks" and r.rules.same_family(p.colour, partner):
        s += 1
    if slot == "belt" and partner is not None:
        s += 3 if r.rules.same_family(p.colour, partner) else -1
    if r.code.sets_whole and any(_whole(r.view, parts) for _, parts in _sets_of(r.view, p.id)):
        s += 2
    return s


def _score(r: _Run, slot: str, unit: Unit) -> float:
    ps = [r.p(i) for i in unit]
    return sum(_piece_score(r, slot, p) + _match_score(r, slot, p) for p in ps) / len(ps)


# ---- the words -----------------------------------------------------------------------------------
def _gap(r: _Run, slot: str, step: str | None, removed: list[Unit]) -> str:
    words, code = r.rules.slot_words_of(slot), r.rules.code_words(r.ask.code)
    ids = [i for u in removed for i in u]
    if step == "available":
        qual = "formal " if r.code.target >= 4 and slot in FORMAL_SLOTS else ""
        return f"No ready {qual}{words}: {texts.states_line([r.p(i) for i in ids])}."
    head = f"No {words} for {code}: "
    if step is None:
        return f"{head}you have none yet (add one {texts.WHERE})."
    if step == "reserved":
        held = " and ".join(dict.fromkeys(r.ask.reserved.get(i, "") for i in ids))
        verb = "are" if len(ids) > 1 else "is"
        return f"{head}{texts.ids_words(ids)} {verb} reserved for {held}."
    if step == "prefs":
        hits = [h for i in ids if (h := _never_hit(r, r.p(i))) is not None]
        if hits:
            rule = texts.never_words(*hits[0])
            return f'{head}your rule "never {rule}" leaves none ({texts.ids_words(ids)}).'
        return f"{head}you excluded {texts.ids_words(ids)} for this."
    why = {"formality": "none is formal enough", "mess": "none is marked okay to stain"}
    return f"{head}{why.get(step, 'none is rain-ok')} ({texts.ids_words(ids)})."


def _why(r: _Run, slot: str, unit: Unit) -> str:
    ps = [r.p(i) for i in unit]
    head = f"{r.rules.slot_words_of(slot).capitalize()} {texts.ids_words(unit)}: {r.words(unit)}"
    if any(p.private for p in ps):
        return f"{head}."
    bits = []
    if slot in FORMAL_SLOTS:
        bits.append(f"formality {r.rules.formality_of(ps[0])}")
    other = r.picks.get(PARTNER.get(slot, ""))
    if other is not None and _match_score(r, slot, ps[0]) > 0:
        bits.append(f"goes with {texts.ids_words(other.pieces)}")
    if r.ask.rain and all("rain_ok" in p.weather for p in ps):
        bits.append("rain-ok")
    if r.code.mess_ok and all(p.mess_ok for p in ps):
        bits.append("okay to stain")
    if any(p.state == "in_use" for p in ps):
        bits.append("handed on from the plan it is worn for (declared)")
    return f"{head}; {', '.join(bits)}." if bits else f"{head}."


def _header(r: _Run) -> str:
    words = r.rules.code_words(r.ask.code)
    tail = f" for {r.ask.for_words}" if r.ask.for_words else ""
    return f"{words[0].upper()}{words[1:]}{tail}."


# ---- filling -------------------------------------------------------------------------------------
def _slots(r: _Run) -> list[tuple[str, bool]]:
    wanted = dict.fromkeys(r.code.required, True)
    for s in r.code.optional:
        wanted.setdefault(s, False)
    if r.ask.rain:
        wanted["outer"] = bool(r.ask.outdoor) or wanted.get("outer", False)
    elif wanted.get("outer") is False and (r.ask.hot or not (r.ask.cold or r.code.target >= 4)):
        del wanted["outer"]
    return [(s, wanted[s]) for s in FILL_ORDER if s in wanted]


def _take(r: _Run, slot: str, unit: Unit, *, locked: bool) -> None:
    r.picks[slot] = Pick(slot, unit, locked)
    r.reasons.append(_why(r, slot, unit))
    for pid in unit:
        _place_mates(r, pid)
        _stale(r, r.p(pid))


def _place_mates(r: _Run, pid: str) -> None:
    for sid, parts in _sets_of(r.view, pid):
        mates = [x for x, _ in parts if x != pid and x in r.view.pieces]
        if not _whole(r.view, parts):
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
                r.reasons.append(_why(r, slot, (x,)))
        ids = texts.ids_words([x for x, _ in parts])
        r.reasons.append(f"The set {sid} is complete: {ids} are ready.")


def _stale(r: _Run, p: Piece) -> None:
    seen = p.place_at
    if r.ask.stale_before is None or seen is None or seen >= r.ask.stale_before:
        return
    r.compromises.append(
        f"Check that {texts.piece_words(p)} ({p.id}) is still in its place: not seen since "
        f"{texts.date_words(seen.date())}."
    )


def _why_not(r: _Run, unit: Unit) -> str:
    held = [r.ask.reserved[i] for i in unit if i in r.ask.reserved]
    if held and all(available(r, r.p(i)) for i in unit):
        return f"reserved for {held[0]}"
    return ", ".join(sorted({STATE_WORDS[r.p(i).state] for i in unit}))


def _kept(r: _Run, slot: str, units: list[Unit], *, locked: bool) -> bool:
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


def _best(r: _Run, slot: str, units: list[Unit]) -> Unit:
    return min(units, key=lambda u: (-_score(r, slot, u), u))


def _fill_slot(r: _Run, slot: str, required: bool, ban: frozenset[str]) -> None:
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
        _take(r, slot, _best(r, slot, left), locked=False)
    elif required:
        r.gaps.append(_gap(r, slot, step, removed))


def _outstanding(r: _Run) -> None:
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
    r = _Run(view, ask, rules)
    r.reasons.append(_header(r))
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
    "Ask",
    "LookOut",
    "Pick",
    "Suggestion",
    "available",
    "fill_one",
    "suggest",
]
