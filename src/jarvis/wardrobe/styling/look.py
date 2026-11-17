# src/jarvis/wardrobe/styling/look.py
"""R13 D12: the engine's records (pure): what a look is asked for (`Ask`), what it holds (`Pick`,
`LookOut`, `Suggestion`) and one run's working state (`Run`), with the set and rule helpers the
engine (`engine.py`) and its ranking and words (`rank.py`) share."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, tzinfo

from jarvis.wardrobe.model import Piece, WardrobeView
from jarvis.wardrobe.states import wearable_set
from jarvis.wardrobe.styling import texts
from jarvis.wardrobe.styling.rules import CodeRule, Rules

Unit = tuple[str, ...]
Parts = tuple[tuple[str, bool], ...]
FILL_ORDER = (
    *("top", "bottom", "shoes", "socks", "belt", "watch"),
    *("outer", "base", "underwear", "tie", "cap", "scarf"),
)
FORMAL_SLOTS = frozenset({"top", "bottom", "shoes", "outer"})
PRIVATE_SLOTS = frozenset({"base", "underwear"})
PARTNER = {"bottom": "top", "outer": "top", "socks": "bottom", "belt": "shoes"}


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
    earlier: frozenset[str] = frozenset()  # held by an earlier plan the same day: shareable
    never: tuple[tuple[str, str], ...] = ()
    excluded: frozenset[str] = frozenset()
    likes: frozenset[str] = frozenset()
    avoids: frozenset[str] = frozenset()
    stale_before: datetime | None = None
    for_words: str = ""  # "your 10:00 event"
    zone: tzinfo = UTC  # his zone: every day the engine names is his local day (D15, M2)


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
class Run:
    view: WardrobeView
    ask: Ask
    rules: Rules
    picks: dict[str, Pick] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    compromises: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    proposed: list[Unit] = field(default_factory=list)  # a shared base to propose (M5)

    @property
    def code(self) -> CodeRule:
        return self.rules.codes[self.ask.code]

    def p(self, pid: str) -> Piece:
        return self.view.pieces[pid]

    def words(self, unit: Sequence[str]) -> str:
        return texts.unit_words([self.p(i) for i in unit])


def sets_of(view: WardrobeView, pid: str) -> list[tuple[str, Parts]]:
    return [
        (s.id, tuple((x.piece, x.alone) for x in s.parts))
        for s in view.sets.values()
        if any(x.piece == pid for x in s.parts)
    ]


def whole(view: WardrobeView, parts: Parts) -> bool:
    states = [(view.pieces[x].state if x in view.pieces else None, a) for x, a in parts]
    return wearable_set(states)[0]


def never_hit(r: Run, p: Piece) -> tuple[str, str] | None:
    own = {"colour": p.colour, "pattern": p.pattern, "type": p.type}
    for feature, value in r.ask.never:
        got = own[feature] if feature in own else p.features.get(feature)
        if got == value:
            return feature, value
    return None


def covered(view: WardrobeView, slot: str, pieces: Sequence[str]) -> bool:
    """R13.1 AVT-14: a private slot, or one holding a private (or unknown) piece, is never drawn
    or named as itself. The ONE rule: row 388's card and the figure's look both ask here (R13.1
    integrated review M5)."""
    if slot in PRIVATE_SLOTS:
        return True
    return any((p := view.pieces.get(i)) is None or p.private for i in pieces)


__all__ = [
    "FILL_ORDER",
    "FORMAL_SLOTS",
    "PARTNER",
    "PRIVATE_SLOTS",
    "Ask",
    "LookOut",
    "Parts",
    "Pick",
    "Run",
    "Suggestion",
    "Unit",
    "covered",
    "never_hit",
    "sets_of",
    "whole",
]
