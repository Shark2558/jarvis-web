# src/jarvis/helpers/kitchen/phrases.py
"""The kitchen's No-AI phrasebook (docs/plans/r11-free-helpers.md D1, D18). Tried before every
older No-AI pattern; each pattern is anchored (the whole message), uses the kitchen's own nouns
(pantry, recipe, groceries, nutrition, cooking / washing-up time, diet) and ends in a kitchen tool,
which still goes through the gateway (policy, audit, cards: the calendar blocks are always a card).
Anything else is left to the other routers (None). Arguments are strings, as `NoAICall` wants.

    what's in my pantry / show my pantry             pantry_list
    add rice, dal and onions to my pantry            pantry_add(items)
    remove onions from my pantry                     pantry_remove(items)
    what can I cook (tonight) (with paneer)          recipe_suggest(with): saved recipes, AI off
    suggest a recipe / recipe ideas                  recipe_suggest
    show my (saved) recipes                          recipe_list
    calories in 200 g rice, 100 g dal                nutrition_of(ingredients)
    nutrition of avial                               nutrition_of(recipe)
    full nutrition for dal                           nutrition_of(recipe, detail=full)
    how much did I spend on groceries (this month | last month | in March)   spend_month(month)
    block (my) cooking (and washing-up) time         calendar_kitchen_blocks(only)
    set my diet to vegetarian / I am eggetarian      kitchen_settings(diet)
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime

from jarvis.offline.rules import NoAICall, NoAIRoute, NoAIRouter

_I = re.IGNORECASE
_LEAD = r"^\s*(?:jarvis[,\s]+)?(?:please\s+)?"
_END = r"\s*(?:please)?\s*[?.!]*\s*$"
_MY = r"(?:my|the)"
PANTRY_LIST = re.compile(
    _LEAD
    + rf"(?:(?:what(?:'s|\s+is)\s+in|show(?:\s+me)?|list|read|check)\s+)?{_MY}\s+pantry"
    + _END,
    _I,
)
PANTRY_ADD = re.compile(
    _LEAD + rf"(?:add|put)\s+(?P<items>.+?)\s+(?:to|in|into)\s+{_MY}\s+pantry" + _END, _I
)
PANTRY_REMOVE = re.compile(
    _LEAD
    + rf"(?:remove|take|delete)\s+(?P<items>.+?)\s+(?:from|off|out\s+of)\s+{_MY}\s+pantry"
    + _END,
    _I,
)
SUGGEST = re.compile(
    _LEAD + r"(?:what\s+(?:can|could|should|shall)\s+i\s+(?:cook|make)"
    r"(?:\s+(?:today|tonight|now))?(?:\s+for\s+(?:breakfast|lunch|dinner|supper))?"
    r"(?:\s+with\s+(?P<with>.+?))?"
    r"|(?:suggest|give\s+me)\s+(?:a\s+)?(?:recipe|dish)(?:\s+ideas?)?|recipe\s+ideas?)" + _END,
    _I,
)
RECIPES = re.compile(
    _LEAD + r"(?:(?:show|list|read)\s+(?:me\s+)?)?my\s+(?:saved\s+)?recipes" + _END, _I
)
NUTRITION = re.compile(
    _LEAD + r"(?:(?:what(?:'s|\s+is)\s+the\s+)?(?P<full>(?:full|complete|all(?:\s+the)?)\s+)?"
    r"(?:nutrition|nutrients|calories|kcal)\s+(?:in|of|for)"
    r"|how\s+many\s+calories\s+(?:are\s+)?in)\s+(?P<what>.+?)" + _END,
    _I,
)
SPEND = re.compile(
    _LEAD + r"(?:how\s+much\s+(?:did|have)\s+i\s+spen[dt]\s+on\s+groceries"
    r"|(?:show\s+)?(?:my\s+)?grocery\s+(?:spend|spending|bills?))"
    r"(?:\s+(?P<when>this\s+month|last\s+month|in\s+(?P<mon>[a-z]+)(?:\s+(?P<year>\d{4}))?))?"
    + _END,
    _I,
)
BLOCKS = re.compile(
    _LEAD + r"(?:block|schedule|add|put)\s+(?:my\s+)?"
    r"(?P<what>cooking\s+and\s+washing[\s-]?up|cooking|washing[\s-]?up)\s+(?:time|blocks?|slots?)"
    r"(?:\s+(?:in|on|to)\s+(?:my\s+)?calendar)?" + _END,
    _I,
)
DIET = re.compile(
    _LEAD + r"(?:set\s+my\s+diet\s+to|i(?:'m|\s+am)(?:\s+an?)?)\s+"
    r"(?P<diet>veg|vegetarian|eggetarian|non[\s-]?veg(?:etarian)?)" + _END,
    _I,
)
_GRAMS = re.compile(r"\d\s*(?:g|gm|gms|grams?|kg|kgs)\b", _I)
_FULL = "january february march april may june july august september october november december"
MONTHS = {name: i for i, name in enumerate(_FULL.split(), 1)}
MONTHS.update({**{name[:3]: i for name, i in MONTHS.items()}, "sept": 9})


def _one(tool: str, **args: str) -> NoAIRoute:
    return NoAIRoute((NoAICall(tool, {k: v for k, v in args.items() if v}),))


def _month(m: re.Match[str], now: datetime) -> str | None:
    when = " ".join((m.group("when") or "this month").casefold().split())
    y, mm = now.year, now.month
    if when == "last month":
        y, mm = (y, mm - 1) if mm > 1 else (y - 1, 12)
    elif when != "this month":
        found = MONTHS.get((m.group("mon") or "").casefold())
        if found is None:
            return None
        mm = found
        y = int(m.group("year")) if m.group("year") else (y if mm <= now.month else y - 1)
    return f"{y:04d}-{mm:02d}"


def _spend(text: str, now: datetime) -> NoAIRoute | None:
    m = SPEND.match(text)
    if m is None:
        return None
    month = _month(m, now)
    return _one("spend_month", month=month) if month else None


def _nutrition(text: str, now: datetime) -> NoAIRoute | None:
    m = NUTRITION.match(text)
    if m is None:
        return None
    what = m.group("what").strip()
    key = "ingredients" if _GRAMS.search(what) else "recipe"
    full = m.group("full") is not None  # I1: "full nutrition for dal", "all nutrients in ..."
    return _one("nutrition_of", **{key: what, "detail": "full" if full else ""})


def _blocks(text: str, now: datetime) -> NoAIRoute | None:
    m = BLOCKS.match(text)
    if m is None:
        return None
    what = m.group("what").casefold()
    only = "both" if " and " in what else ("cooking" if what.startswith("cook") else "washing_up")
    return _one("calendar_kitchen_blocks", only=only)


def _diet(text: str, now: datetime) -> NoAIRoute | None:
    m = DIET.match(text)
    if m is None:
        return None
    word = m.group("diet").casefold()
    diet = "egg" if word.startswith("egg") else ("nonveg" if word.startswith("non") else "veg")
    return _one("kitchen_settings", diet=diet)


def _simple(text: str, now: datetime) -> NoAIRoute | None:
    if PANTRY_LIST.match(text):
        return _one("pantry_list")
    if (m := PANTRY_ADD.match(text)) is not None:
        return _one("pantry_add", items=m.group("items").strip())
    if (m := PANTRY_REMOVE.match(text)) is not None:
        return _one("pantry_remove", items=m.group("items").strip())
    if (m := SUGGEST.match(text)) is not None:
        return _one("recipe_suggest", **{"with": (m.group("with") or "").strip()})
    if RECIPES.match(text):
        return _one("recipe_list")
    return None


STEPS: tuple[Callable[[str, datetime], NoAIRoute | None], ...] = (
    _simple,
    _nutrition,
    _spend,
    _blocks,
    _diet,
)


def route(text: str, now: datetime) -> NoAIRoute | None:
    """The kitchen's route for `text` (the owner's words, `now` in his zone), or None."""
    one = " ".join(str(text)[:500].split())
    for step in STEPS:
        if (found := step(one, now)) is not None:
            return found
    return None


PHRASES: tuple[NoAIRouter, ...] = (route,)

__all__ = ["PHRASES", "route"]
