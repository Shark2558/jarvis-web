# src/jarvis/helpers/kitchen/diet.py
"""The diet check (docs/plans/r11-free-helpers.md D15, Risks "Diet mistakes offend"). Code, not
the model, has the last word, and it is conservative: when in doubt it refuses. A false refusal
only means "I couldn't find a recipe that fits"; a false pass serves meat to a vegetarian.

Two checks, both needed for a new idea:
- The deny check (`hits`): a recipe whose title, cuisine, ingredients or steps hold a meat, fish,
  seafood or egg stem is refused, whatever the model says its diet is. The text is normalised
  first: NFKD, casefold, combining marks and zero-width / format characters dropped, Cyrillic and
  Greek look-alikes read as Latin letters; stems match inside words, and the long ones also on a
  copy with every space and sign removed ("Chic ken"). The lists and the reasons are in
  `diet_words`. "veg" forbids meat, fish and egg; "egg" forbids meat and fish; "nonveg" nothing.
- The allow-list (`outside_pantry`, when `allows` is given his pantry): every ingredient of a new
  idea for a veg or egg kitchen must be one of his pantry items, or a fixed staple (salt, water,
  oils, ghee, sugar, the common spices), after cooking words ("chopped", "fresh") are dropped. An
  ingredient may be more general than a pantry item ("rice" for "basmati rice"), never more
  specific ("rice wine"). Saved recipes are his own and get the deny check only.

`DIET_CHECK` exists only so the eval can show its negative control (both checks switched off).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from jarvis.groceries.items import norm_key
from jarvis.helpers.kitchen.diet_words import (
    CHILLU,
    CONFUSABLES,
    EGG_ANYWHERE,
    EGG_NATIVE,
    EGG_WORD_START,
    HARMLESS,
    MEAT_ANYWHERE,
    MEAT_NATIVE,
    MEAT_WORD_START,
    QUALIFIERS,
    STAPLES,
)
from jarvis.helpers.kitchen.models import Diet, Recipe

DIET_CHECK = True
RANK: dict[Diet, int] = {"veg": 0, "egg": 1, "nonveg": 2}
FLAT_MIN = 5  # stems this long are also looked for with every space and sign removed
_CONFUSE = str.maketrans(CONFUSABLES)
_HARMLESS = re.compile("|".join(HARMLESS))
_NOT_LETTER = re.compile(r"[^a-z]+")
_PAREN = re.compile(r"\([^)]*\)")
_DROP = frozenset({"Mn", "Me", "Cf"})


def latin_form(text: str) -> str:
    """Casefolded, decomposed, marks and format characters dropped, look-alikes as Latin."""
    t = unicodedata.normalize("NFKD", str(text).casefold())
    t = "".join(ch for ch in t if unicodedata.category(ch) not in _DROP)
    return _HARMLESS.sub(" ", t.translate(_CONFUSE).replace("_", " "))


def native_form(text: str) -> str:
    """Indian scripts kept composed (NFKC), old-style chillu letters joined, format chars gone."""
    t = unicodedata.normalize("NFKC", str(text)).casefold()
    for old, new in CHILLU.items():
        t = t.replace(old, new)
    return "".join(ch for ch in t if unicodedata.category(ch) != "Cf")


def _flat_native(text: str) -> str:
    return "".join(ch for ch in text if unicodedata.category(ch)[0] not in "PSZC")


@dataclass(frozen=True)
class _Words:
    anywhere: re.Pattern[str]
    start: re.Pattern[str]
    flat: tuple[str, ...]
    native: tuple[str, ...]

    @classmethod
    def of(cls, anywhere: Sequence[str], start: Sequence[str], native: Sequence[str]) -> _Words:
        def alts(words: Iterable[str]) -> str:
            return "|".join(sorted((re.escape(w) for w in words), key=len, reverse=True))

        flat = tuple(_NOT_LETTER.sub("", w) for w in anywhere)
        return cls(
            re.compile(alts(anywhere)),
            re.compile(r"\b(?:" + alts(start) + ")"),
            tuple(w for w in flat if len(w) >= FLAT_MIN),
            tuple(unicodedata.normalize("NFKC", w) for w in native),
        )

    def found(self, latin: str, flat: str, native: str, native_flat: str) -> set[str]:
        out = {m.group(0) for m in self.anywhere.finditer(latin)}
        out |= {m.group(0) for m in self.start.finditer(latin)}
        out |= {w for w in self.flat if w in flat}
        return out | {w for w in self.native if w in native or w in native_flat}


_MEAT = _Words.of(MEAT_ANYWHERE, MEAT_WORD_START, MEAT_NATIVE)
_EGG = _Words.of(EGG_ANYWHERE, EGG_WORD_START, EGG_NATIVE)


def hits(text: str, diet: Diet) -> list[str]:
    """The stems in `text` a `diet` kitchen must never be served (sorted, lower case)."""
    if diet == "nonveg":
        return []
    latin = latin_form(text)
    native = native_form(text)
    forms = (latin, _NOT_LETTER.sub("", latin), native, _flat_native(native))
    found = _MEAT.found(*forms)
    if diet == "veg":
        found |= _EGG.found(*forms)
    return sorted(found)


def recipe_hits(recipe: Recipe, diet: Diet) -> list[str]:
    parts = [recipe.title, recipe.cuisine, *(i.name for i in recipe.ingredients), *recipe.steps]
    return hits("\n".join(parts), diet)


def core(name: str) -> frozenset[str]:
    """An ingredient's words without cooking words: "Chopped tomatoes" -> {"tomato"}."""
    words = [w for w in norm_key(_PAREN.sub(" ", name)).split() if w not in QUALIFIERS]
    return frozenset(norm_key(" ".join(words)).split()) if words else frozenset()


_STAPLES = tuple(core(s) for s in STAPLES)


def outside_pantry(recipe: Recipe, pantry: Iterable[str]) -> list[str]:
    """The ingredients that are neither in his pantry nor a staple (their own words)."""
    known = (*(c for c in map(core, pantry) if c), *_STAPLES)

    def ok(name: str) -> bool:
        c = core(name)
        return bool(c) and any(c <= k for k in known)

    return [i.name for i in recipe.ingredients if not ok(i.name)]


def allows(recipe: Recipe, diet: Diet, *, pantry: Iterable[str] | None = None) -> bool:
    """True when `recipe` may be shown to a `diet` kitchen: its own diet is at least as strict,
    none of its words is forbidden and, given his `pantry` (a new idea, a veg or egg kitchen),
    it uses only the pantry and the staples. Always True with the check switched off (eval)."""
    if not DIET_CHECK:
        return True
    if RANK[recipe.diet] > RANK[diet] or recipe_hits(recipe, diet):
        return False
    return pantry is None or diet == "nonveg" or not outside_pantry(recipe, pantry)


def stricter(a: Diet, b: Diet | None) -> Diet:
    return a if b is None or RANK[a] <= RANK[b] else b


__all__ = [
    "DIET_CHECK",
    "RANK",
    "allows",
    "core",
    "hits",
    "latin_form",
    "native_form",
    "outside_pantry",
    "recipe_hits",
    "stricter",
]
