# src/jarvis/helpers/kitchen/nutrition.py
"""Rough nutrition per dish (docs/plans/r11-free-helpers.md D15, item 14). Plain code, no model.

The values come from a bundled subset of USDA FoodData Central (CC0 1.0, public domain; the
Indian Nutrient Databank can't be used: no licence), `data/fdc_subset.json`, built once by
`scripts/kitchen_fdc_subset.py` from the official FDC CSV download (per 100 g of the raw food:
kcal, protein, fat, carbohydrate, fibre, sodium). A dish is the sum of grams x per-100 g over the
ingredients found; an ingredient that isn't in the subset is named, never guessed, and a value
FDC doesn't give counts as nothing. Always said as "about", on a raw-ingredient basis, with the
attribution. Until the subset is installed (its `installed` flag), every answer is
`NOT_INSTALLED`. Names are matched by the groceries key only (`groceries.items.norm_key`: case,
plurals, curd = yogurt ...) against each food's own names: "coconut milk" is never read as
"milk", nor "sweet potato" as "potato". An ingredient not found is listed as "not found" and the
answer says the total is partial.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from jarvis.groceries.items import norm_key
from jarvis.helpers.kitchen.models import GRAMS_MAX, Ingredient, plain
from jarvis.logging import get_logger

log = get_logger(__name__)

DATA = Path(__file__).resolve().parent / "data" / "fdc_subset.json"
NUTRIENTS = ("kcal", "protein_g", "fat_g", "carb_g", "fibre_g", "sodium_mg")
MAX_FOODS = 1_000
MAX_FILE_BYTES = 2_000_000
SOURCE_LINE = "USDA FoodData Central (public domain), raw ingredients"
ATTRIBUTION = f"Nutrient values: {SOURCE_LINE}; a rough guide."
NOT_INSTALLED = "Nutrition data isn't installed yet, Sir (the USDA FoodData Central subset)."
_UNITS = {"g": 1, "gm": 1, "gms": 1, "gram": 1, "grams": 1, "kg": 1000, "kgs": 1000}
_AMOUNT = r"(\d+(?:\.\d+)?)\s*(kgs?|grams?|gms?|g)\b"
_LEADING = re.compile(rf"^\s*{_AMOUNT}\s*(?:of\s+)?(.+?)\s*$", re.IGNORECASE)
_TRAILING = re.compile(rf"^\s*(.+?)\s*[-:,]?\s*{_AMOUNT}\s*$", re.IGNORECASE)
MAX_TYPED = 30
MAX_NAMED = 5


@dataclass(frozen=True)
class Food:
    key: str
    fdc_id: int
    names: tuple[str, ...]
    per100: Mapping[str, float | None]


@dataclass(frozen=True)
class DishNutrition:
    installed: bool
    totals: Mapping[str, float] = field(default_factory=dict)
    matched: int = 0
    unmatched: tuple[str, ...] = ()
    grams: int = 0


def _food(raw: object) -> Food | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("key"), str):
        return None
    got = raw.get("per100g")
    per: dict[str, object] = got if isinstance(got, dict) else {}
    values: dict[str, float | None] = {}
    for n in NUTRIENTS:
        v = per.get(n)
        ok = isinstance(v, int | float) and not isinstance(v, bool) and 0 <= v < 100_000
        values[n] = float(v) if ok and isinstance(v, int | float) else None
    names = tuple(str(x) for x in raw.get("names") or () if isinstance(x, str))
    fid = raw.get("fdc_id")
    return Food(raw["key"], fid if isinstance(fid, int) else 0, (raw["key"], *names), values)


class Nutrition:
    def __init__(self, foods: Sequence[Food], *, installed: bool) -> None:
        self.installed = installed and bool(foods)
        self._by_name: dict[str, Food] = {}
        for f in foods:
            for name in f.names:
                self._by_name.setdefault(norm_key(name), f)

    @classmethod
    def load(cls, path: Path = DATA) -> Nutrition:
        """The subset at `path`; a missing, oversized or broken file reads as not installed."""
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                raise ValueError("too big")
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("nutrition data unreadable", extra={"error": type(exc).__name__})
            return cls((), installed=False)
        foods = [f for f in map(_food, (raw.get("foods") or [])[:MAX_FOODS]) if f is not None]
        return cls(foods, installed=raw.get("installed") is True)

    def find(self, name: str) -> Food | None:
        return self._by_name.get(norm_key(name))

    def dish(self, ingredients: Sequence[Ingredient]) -> DishNutrition:
        if not self.installed:
            return DishNutrition(installed=False)
        totals = dict.fromkeys(NUTRIENTS, 0.0)
        unmatched: list[str] = []
        for ing in ingredients:
            food = self.find(ing.name)
            if food is None:
                unmatched.append(ing.name)
                continue
            for n in NUTRIENTS:
                totals[n] += (food.per100.get(n) or 0.0) * ing.grams / 100
        matched = len(ingredients) - len(unmatched)
        grams = sum(i.grams for i in ingredients)
        return DishNutrition(True, totals, matched, tuple(unmatched), grams)


def describe(d: DishNutrition) -> str:
    """One fixed-template line: "About 520 kcal, 18 g protein, ... (USDA ...)"."""
    if not d.installed:
        return NOT_INSTALLED
    if d.matched == 0:
        return f"None of those ingredients is in the nutrition data, Sir ({SOURCE_LINE})."
    t = d.totals
    line = (
        f"About {round(t['kcal'])} kcal, {round(t['protein_g'])} g protein, "
        f"{round(t['fat_g'])} g fat, {round(t['carb_g'])} g carbohydrate, "
        f"{round(t['fibre_g'])} g fibre, {round(t['sodium_mg'])} mg sodium"
    )
    return f"{line}{_partial(d)}. {ATTRIBUTION}"


def _partial(d: DishNutrition) -> str:
    if not d.unmatched:
        return ""
    total = d.matched + len(d.unmatched)
    names = ", ".join(d.unmatched[:MAX_NAMED])
    more = f" and {len(d.unmatched) - MAX_NAMED} more" if len(d.unmatched) > MAX_NAMED else ""
    return f". A partial total: {d.matched} of {total} ingredients found; not found: {names}{more}"


def _one(part: str) -> Ingredient:
    if (m := _LEADING.match(part)) is not None:
        qty, unit, name = m.groups()
    elif (m := _TRAILING.match(part)) is not None:
        name, qty, unit = m.groups()
    else:
        raise ValueError("Give the grams for each ingredient, such as '200 g rice'.")
    grams = round(float(qty) * _UNITS.get(unit.lower(), 1))
    if not 1 <= grams <= GRAMS_MAX:
        raise ValueError(f"Each ingredient must be from 1 to {GRAMS_MAX} g.")
    try:
        return Ingredient(name=name, grams=grams)
    except ValidationError as exc:
        raise plain(exc) from None


def parse_ingredients(text: str) -> tuple[Ingredient, ...]:
    """'200 g rice, 50g toor dal; 1 kg potato, onion 80 g' -> ingredients with grams."""
    parts = [p for p in re.split(r"[,;\n]", str(text)[:2_000]) if p.strip()]
    if not parts or len(parts) > MAX_TYPED:
        raise ValueError(f"Give 1 to {MAX_TYPED} ingredients, such as '200 g rice, 100 g dal'")
    return tuple(_one(p) for p in parts)


__all__ = [
    "ATTRIBUTION",
    "DATA",
    "NOT_INSTALLED",
    "NUTRIENTS",
    "DishNutrition",
    "Food",
    "Nutrition",
    "describe",
    "parse_ingredients",
]
