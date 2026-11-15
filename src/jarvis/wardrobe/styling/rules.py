# src/jarvis/wardrobe/styling/rules.py
"""R13 D12 (docs/plans/r13-wardrobe.md): the styling rules as data (`rules.json`), checked at start.

- slots (top, bottom, shoes, socks, belt, watch, outer, base, underwear, tie, cap, scarf) and the
  types each takes (`model.TYPES` words only); shoes and socks are worn as pairs;
- dress codes (business formal, business casual, smart casual, casual, festive, okay to stain,
  sport): the slots each requires and allows, the types per slot, the formality it aims at and
  its floor, "okay to stain" only (Holi), sets checked whole (festive);
- event rules: the words that, matched in code only (a calendar title is never stored), name an
  occasion and its dress code; outdoor and indoor words for a location;
- a small colour-pairing table, colour families (a belt matches the shoes), heat and cold;
- the rewear rule (`after_wear`): trousers, jeans, outerwear, belts, shoes and the watch are worn
  again (Ready); shirts, T-shirts, vests, underwear, socks and anything else go to the laundry.

`load_rules()` refuses a file that names an unknown type, slot or code (`RulesError`): the part is
then "setup failed" and the other parts run. Pure: no clock, no I/O beyond reading the file.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from jarvis.wardrobe.model import COLOURS, TYPES, Piece
from jarvis.wardrobe.states import State

KNOWN_TYPES = frozenset(t for types in TYPES.values() for t in types)
_WORD = re.compile(r"[a-z0-9]+")


class RulesError(ValueError):
    """The rules file failed its check (the part is left out: "setup failed")."""


class _M(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CodeRule(_M):
    words: str = Field(min_length=1, max_length=40)
    target: int = Field(ge=1, le=5)
    min: int = Field(ge=1, le=5)
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    types: Mapping[str, tuple[str, ...]] = Field(default_factory=dict)
    occasion: str | None = None
    mess_ok: bool = False
    sets_whole: bool = False


class EventRule(_M):
    code: str
    words: tuple[str, ...] = Field(min_length=1)


class Rules(_M):
    version: int = Field(ge=1)
    slots: Mapping[str, tuple[str, ...]]
    slot_words: Mapping[str, str]
    paired: tuple[str, ...]
    formality: Mapping[str, int]
    codes: Mapping[str, CodeRule]
    events: Mapping[str, EventRule]
    event_order: tuple[str, ...]
    default_code: str
    event_code: str
    outdoor_words: tuple[str, ...]
    indoor_words: tuple[str, ...]
    hot_c: float
    cold_c: float
    light_fabrics: tuple[str, ...]
    neutral: tuple[str, ...]
    pairing: tuple[tuple[str, str], ...]
    families: Mapping[str, str]
    reusable: tuple[str, ...]
    recent_days: int = Field(ge=0, le=30)

    @model_validator(mode="after")
    def _check(self) -> Rules:
        _check_slots(self)
        _check_codes(self)
        colours = {*self.neutral, *(c for p in self.pairing for c in p), *self.families}
        if not colours <= set(COLOURS):
            raise ValueError("a colour that is not on the fixed list")
        if not set(self.reusable) <= KNOWN_TYPES:
            raise ValueError("the rewear rule names an unknown type")
        return self

    # ---- reading the rules ------------------------------------------------------------------
    def slot_of(self, type_: str) -> str | None:
        return next((s for s, types in self.slots.items() if type_ in types), None)

    def types_for(self, code: str, slot: str) -> tuple[str, ...]:
        return self.codes[code].types.get(slot, self.slots[slot])

    def formality_of(self, piece: Piece) -> int:
        return piece.formality or self.formality.get(piece.type, 2)

    def reusable_piece(self, piece: Piece) -> bool:
        return piece.type in self.reusable

    def after_wear(self, piece: Piece) -> State:
        """The rewear rule: Ready again, or to the laundry (D12; the owner's default)."""
        return "ready" if self.reusable_piece(piece) else "in_laundry"

    def occasion_of(self, text: str) -> str | None:
        """The occasion his words (or an event's title, in memory only) name, else None."""
        words = " ".join(_WORD.findall(text.lower()))
        padded = f" {words} "
        for occasion in self.event_order:
            if any(f" {w} " in padded for w in self.events[occasion].words):
                return occasion
        return None

    def code_of(self, occasion: str | None, *, event: bool) -> str:
        if occasion is not None:
            return self.events[occasion].code
        return self.event_code if event else self.default_code

    def outdoor_of(self, location: str) -> bool | None:
        words = set(_WORD.findall(location.lower()))
        if words & set(self.outdoor_words):
            return True
        if words & set(self.indoor_words):
            return False
        return None

    def pairs_with(self, a: str | None, b: str | None) -> int:
        """+2 a listed pair, +1 a neutral beside another colour, 0 unknown, -1 two loud colours."""
        if a is None or b is None:
            return 0
        if (a, b) in self.pairing or (b, a) in self.pairing:
            return 2
        if a == b:
            return 1 if a in self.neutral else -1
        if a in self.neutral or b in self.neutral:
            return 1
        return -1

    def same_family(self, a: str | None, b: str | None) -> bool:
        if a is None or b is None:
            return False
        return self.families.get(a, a) == self.families.get(b, b)

    def code_words(self, code: str) -> str:
        return self.codes[code].words

    def slot_words_of(self, slot: str) -> str:
        return self.slot_words.get(slot, slot)


def _check_slots(r: Rules) -> None:
    for slot, types in r.slots.items():
        if not types or not set(types) <= KNOWN_TYPES:
            raise ValueError(f"slot {slot} names an unknown type")
    if set(r.slot_words) != set(r.slots) or not set(r.paired) <= set(r.slots):
        raise ValueError("every slot needs its words; paired slots must be slots")
    if not set(r.formality) <= KNOWN_TYPES:
        raise ValueError("formality names an unknown type")


def _check_codes(r: Rules) -> None:
    for name, code in r.codes.items():
        slots = (*code.required, *code.optional, *code.types)
        if not set(slots) <= set(r.slots) or code.min > code.target:
            raise ValueError(f"code {name} names an unknown slot")
        for slot, types in code.types.items():
            if not set(types) <= set(r.slots[slot]):
                raise ValueError(f"code {name} puts a type in the wrong slot")
    codes = {r.default_code, r.event_code, *(e.code for e in r.events.values())}
    if not codes <= set(r.codes) or set(r.event_order) != set(r.events):
        raise ValueError("an event names an unknown code, or the order misses one")


def _source(path: Path | None) -> str:
    if path is not None:
        return path.read_text(encoding="utf-8")
    return (files("jarvis.wardrobe.styling") / "rules.json").read_text(encoding="utf-8")


def load_rules(path: Path | None = None) -> Rules:
    """The checked rules (`rules.json` beside this file unless `path`); `RulesError` if not."""
    try:
        raw: Any = json.loads(_source(path))
        return Rules.model_validate(raw)
    except (OSError, ValueError, ValidationError) as exc:
        raise RulesError(f"the styling rules failed their check: {type(exc).__name__}") from exc


__all__ = ["KNOWN_TYPES", "CodeRule", "EventRule", "Rules", "RulesError", "load_rules"]
