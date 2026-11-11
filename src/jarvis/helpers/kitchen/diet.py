# src/jarvis/helpers/kitchen/diet.py
"""The diet check (docs/plans/r11-free-helpers.md D15, Risks "Diet mistakes offend"). Code, not
the model, has the last word: a recipe for a vegetarian kitchen whose title, ingredients or steps
name meat, fish, seafood or egg is refused, whatever the model says its diet is.

`hits(text, diet)` lists the forbidden words found (English, Hindi, Malayalam, Odia, Tamil and
Bengali, in Latin letters and in their own scripts). "veg" forbids meat, fish and egg; "egg"
forbids meat and fish; "nonveg" forbids nothing. A few look-alikes are vegetarian and pass
(eggplant, eggless, egg-free, kidney beans, coconut meat). Words in Latin letters match whole
words (with a plural "s"/"es"); words in Indian scripts match anywhere (those scripts join
signs to letters, so a word edge can't be found reliably). When in doubt it refuses: a vegetable
dish wrongly refused costs one more try; meat in a vegetarian kitchen is never acceptable.

`DIET_CHECK` exists only so the eval can show its negative control (the check switched off).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from jarvis.helpers.kitchen.models import Diet, Recipe

DIET_CHECK = True
RANK: dict[Diet, int] = {"veg": 0, "egg": 1, "nonveg": 2}

MEAT_WORDS = (
    # English
    "chicken", "mutton", "lamb", "beef", "pork", "bacon", "ham", "sausage", "salami",
    "pepperoni", "veal", "venison", "steak", "turkey", "duck", "quail", "meat",
    "goat meat", "liver", "lard", "gelatin", "gelatine", "bone broth", "fish", "salmon", "tuna",
    "sardine", "mackerel", "pomfret", "hilsa", "rohu", "katla", "surmai", "anchovy",
    "anchovies", "cod", "tilapia", "basa", "shrimp", "prawn", "lobster", "crab", "squid",
    "calamari", "octopus", "oyster", "mussel", "clam", "scallop", "caviar", "roe",
    "worcestershire", "seafood",
    # Hindi / Urdu in Latin letters
    "murgh", "murg", "murgi", "gosht", "keema", "kheema", "qeema", "machli", "machhli",
    "macchi", "jhinga", "jheenga", "kaleji", "bakra",
    # Malayalam in Latin letters
    "kozhi", "meen", "chemmeen", "njandu", "kakka", "irachi", "erachi", "pothu",
    "kallummakkaya", "koonthal", "mathi", "ayala", "ayila", "karimeen", "nethili",
    # Odia, Bengali, Tamil in Latin letters
    "machha", "chingudi", "kankada", "mansa", "mangsa", "mangsho", "kukuda", "ilishi", "ilish",
    "maach", "chingri", "eral", "nandu", "bangda", "bombil",
    # Indian scripts (Hindi, Malayalam, Odia, Tamil, Bengali)
    "चिकन", "मुर्ग", "मछली", "गोश्त", "मांस", "झींगा", "कीमा",
    "കോഴി", "മീൻ", "ചെമ്മീൻ", "ഇറച്ചി", "ബീഫ്", "ഞണ്ട്",
    "ମାଛ", "ଚିଙ୍ଗୁଡ଼ି", "ମାଂସ", "କୁକୁଡ଼ା",
    "கோழி", "மீன்", "இறால்", "இறைச்சி",
    "মাছ", "মাংস", "চিংড়ি",
)  # fmt: skip
EGG_WORDS = (
    "egg", "omelette", "omelet", "omlet", "frittata", "quiche", "meringue", "mayonnaise",
    "mayo", "albumen", "anda", "ande", "mutta", "muttai",
    "अंडा", "अंडे", "മുട്ട", "ଅଣ୍ଡା", "முட்டை", "ডিম",
)  # fmt: skip
SAFE = re.compile(
    r"\beggplants?\b|\beggs?[\s-]*free\b|\bkidney\s+beans?\b|\bcoconut\s+meat\b",
    re.IGNORECASE,
)


def _latin(words: Iterable[str]) -> re.Pattern[str]:
    alts = sorted((re.escape(w) for w in words if w.isascii()), key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(alts) + r")(?:e?s)?\b")


def _native(words: Iterable[str]) -> tuple[str, ...]:
    return tuple(unicodedata.normalize("NFC", w) for w in words if not w.isascii())


_MEAT_LATIN, _MEAT_NATIVE = _latin(MEAT_WORDS), _native(MEAT_WORDS)
_EGG_LATIN, _EGG_NATIVE = _latin(EGG_WORDS), _native(EGG_WORDS)


def _found(text: str, latin: re.Pattern[str], native: tuple[str, ...]) -> set[str]:
    found = {m.group(0) for m in latin.finditer(text)}
    return found | {w for w in native if w in text}


def hits(text: str, diet: Diet) -> list[str]:
    """The words in `text` a `diet` kitchen must never be served (sorted, lower case)."""
    if diet == "nonveg":
        return []
    plain = SAFE.sub(" ", unicodedata.normalize("NFC", str(text)).casefold().replace("_", " "))
    found = _found(plain, _MEAT_LATIN, _MEAT_NATIVE)
    if diet == "veg":
        found |= _found(plain, _EGG_LATIN, _EGG_NATIVE)
    return sorted(found)


def recipe_hits(recipe: Recipe, diet: Diet) -> list[str]:
    parts = [recipe.title, *(i.name for i in recipe.ingredients), *recipe.steps]
    return hits("\n".join(parts), diet)


def allows(recipe: Recipe, diet: Diet) -> bool:
    """True when `recipe` may be shown to a `diet` kitchen: its own diet is at least as strict
    and none of its words is forbidden. Always True with the check switched off (eval only)."""
    if not DIET_CHECK:
        return True
    return RANK[recipe.diet] <= RANK[diet] and not recipe_hits(recipe, diet)


def stricter(a: Diet, b: Diet | None) -> Diet:
    return a if b is None or RANK[a] <= RANK[b] else b


__all__ = [
    "DIET_CHECK",
    "EGG_WORDS",
    "MEAT_WORDS",
    "RANK",
    "allows",
    "hits",
    "recipe_hits",
    "stricter",
]
