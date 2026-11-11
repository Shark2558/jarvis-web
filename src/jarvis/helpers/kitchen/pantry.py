# src/jarvis/helpers/kitchen/pantry.py
"""Pure changes to his kitchen (docs/plans/r11-free-helpers.md D15): the pantry, his tastes,
saved recipes and the block plan. No I/O: `service.KitchenService` runs these inside the store's
transaction. Pantry names dedupe by the groceries key (`groceries.items.norm_key`: "Tomatoes" and
"tomato" are one item; curd = yogurt); a quantity in brackets ("Milk (2 L)") is dropped.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from jarvis.groceries.items import norm_key, parse_title
from jarvis.helpers.kitchen.models import (
    MAX_PANTRY,
    MAX_RECIPES,
    BlockPlan,
    Kitchen,
    Prefs,
    Recipe,
    clean,
)

MAX_ITEMS_AT_ONCE = 50
NAME_MAX = 60
_SPLIT = re.compile(r"\s*(?:[,;\n]|\band\b|&)\s*", re.IGNORECASE)


def split_items(value: object) -> list[str]:
    """'rice, toor dal and onions' (or a list of names) -> clean names, his own words."""
    raw = list(value) if isinstance(value, list | tuple) else _SPLIT.split(str(value or "")[:2000])
    names = [parse_title(str(x)).name for x in raw if str(x).strip()]
    if not names:
        raise ValueError("Name at least one item, such as 'rice, toor dal'.")
    if len(names) > MAX_ITEMS_AT_ONCE:
        raise ValueError(f"At most {MAX_ITEMS_AT_ONCE} items at once, Sir.")
    return [clean(n, NAME_MAX) for n in names]


def add_items(k: Kitchen, names: Sequence[str]) -> tuple[Kitchen, list[str], list[str]]:
    """(the new kitchen, names added, names already there)."""
    keys = {norm_key(p) for p in k.pantry}
    added: list[str] = []
    already: list[str] = []
    for name in names:
        key = norm_key(name)
        if key in keys:
            already.append(name)
            continue
        keys.add(key)
        added.append(name)
    if len(k.pantry) + len(added) > MAX_PANTRY:
        raise ValueError(f"Your pantry holds at most {MAX_PANTRY} items, Sir.")
    return k.model_copy(update={"pantry": (*k.pantry, *added)}), added, already


def remove_items(k: Kitchen, names: Sequence[str]) -> tuple[Kitchen, list[str], list[str]]:
    """(the new kitchen, the pantry names taken out, the asked names not in it)."""
    wanted = {norm_key(n): n for n in names}
    removed = [p for p in k.pantry if norm_key(p) in wanted]
    gone = {norm_key(p) for p in removed}
    missing = [n for key, n in wanted.items() if key not in gone]
    kept = tuple(p for p in k.pantry if norm_key(p) not in gone)
    return k.model_copy(update={"pantry": kept}), removed, missing


def set_prefs(k: Kitchen, changes: Mapping[str, Any]) -> Kitchen:
    """His tastes with `changes` applied (validated: ValueError in plain words)."""
    data = {**k.prefs.model_dump(), **{key: v for key, v in changes.items() if v is not None}}
    return k.model_copy(update={"prefs": Prefs.model_validate(data)})


def save_recipe(k: Kitchen, recipe: Recipe) -> tuple[Kitchen, bool]:
    """(the new kitchen, whether one of the same title was replaced)."""
    same = [r for r in k.recipes if r.title.casefold() == recipe.title.casefold()]
    others = tuple(r for r in k.recipes if r not in same)
    if not same and len(others) >= MAX_RECIPES:
        raise ValueError(f"You can keep at most {MAX_RECIPES} recipes, Sir.")
    kept = recipe.model_copy(update={"id": same[0].id}) if same else recipe
    return k.model_copy(update={"recipes": (*others, kept)}), bool(same)


def forget_recipe(k: Kitchen, rid: str) -> tuple[Kitchen, bool]:
    kept = tuple(r for r in k.recipes if r.id != rid)
    return k.model_copy(update={"recipes": kept}), len(kept) != len(k.recipes)


def find_recipe(k: Kitchen, words: str) -> Recipe | None:
    """A saved recipe by its id or its title (case and spaces ignored)."""
    want = " ".join(str(words).casefold().split())
    return next(
        (r for r in k.recipes if want in (r.id, " ".join(r.title.casefold().split()))), None
    )


def set_blocks(k: Kitchen, plan: Mapping[str, Any]) -> Kitchen:
    data = {**k.blocks.model_dump(), **{key: v for key, v in plan.items() if v is not None}}
    return k.model_copy(update={"blocks": BlockPlan.model_validate(data)})


__all__ = [
    "add_items",
    "find_recipe",
    "forget_recipe",
    "remove_items",
    "save_recipe",
    "set_blocks",
    "set_prefs",
    "split_items",
]
