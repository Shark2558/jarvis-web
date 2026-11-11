# src/jarvis/helpers/kitchen/nutrition.py
"""Rough nutrition per dish (docs/plans/r11-free-helpers.md D15, item 14; R11 I1). Plain code.

The values come from bundled data files, read once at start through `importlib.resources`:
`data/fdc_subset.json` is a subset of USDA FoodData Central SR Legacy (CC0 1.0, public domain;
the Indian Nutrient Databank can't be used: no licence), built by `scripts/kitchen_fdc_subset.py`
from the official CSV download: ~565 raw foods of an Indian kitchen, each with EVERY nutrient the
file reports per 100 g (`all`; names and units once in `nutrients`) and the six key values
(`per100g`: kcal, protein, fat, carbohydrate, fibre, sodium).

- **Pluggable sources.** Each food carries its `source` id; a file's `sources` say each one's
  region and label. A lookup prefers a food from a source marked `"region": "IN"` when one is
  installed (another `data/nutrition_*.json`, e.g. ICMR-NIN IFCT 2017 with NIN's written
  permission: none is bundled), then falls back to USDA.
- **Honest labels.** Every answer says "US reference values (USDA FoodData Central); Indian
  varieties and home recipes can differ." (or the Indian source's own label when one was used).
- A dish is the sum of grams x per-100 g over the ingredients found; one not in the data is named,
  never guessed, and a value the data doesn't give counts as nothing. Always "about", on a
  raw-ingredient basis. `describe` gives the six key values (the default), `describe_full` every
  nutrient (on request: "full nutrition for dal"). Until a data file is installed (its
  `installed` flag), every answer is `NOT_INSTALLED`. Names are matched by the groceries key only
  (`groceries.items.norm_key`): "coconut milk" is never read as "milk".
"""

from __future__ import annotations

import functools
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Any

from pydantic import ValidationError

from jarvis.groceries.items import norm_key
from jarvis.helpers.kitchen.models import GRAMS_MAX, Ingredient, plain
from jarvis.logging import get_logger

log = get_logger(__name__)

DATA_DIR: Traversable = files("jarvis.helpers.kitchen").joinpath("data")
DATA: Traversable = DATA_DIR.joinpath("fdc_subset.json")
EXTRA_GLOB = re.compile(r"^nutrition_[a-z0-9_]{1,40}\.json$")  # another source, e.g. Indian values
USDA = "usda_sr_legacy"
NUTRIENTS = ("kcal", "protein_g", "fat_g", "carb_g", "fibre_g", "sodium_mg")
MAX_FOODS = 2_000
MAX_FILE_BYTES = 4_000_000
MAX_VALUE = 100_000.0
LABEL = "US reference values (USDA FoodData Central); Indian varieties and home recipes can differ."
SOURCE_LINE = "USDA FoodData Central (public domain), raw ingredients"
ATTRIBUTION = f"{LABEL} Nutrient values: {SOURCE_LINE}; a rough guide."
NOT_INSTALLED = "Nutrition data isn't installed yet, Sir (the USDA FoodData Central subset)."
UNITS = {"G": "g", "MG": "mg", "UG": "µg", "KCAL": "kcal", "KJ": "kJ", "IU": "IU"}
_UNITS = {"g": 1, "gm": 1, "gms": 1, "gram": 1, "grams": 1, "kg": 1000, "kgs": 1000}
_AMOUNT = r"(\d+(?:\.\d+)?)\s*(kgs?|grams?|gms?|g)\b"
_LEADING = re.compile(rf"^\s*{_AMOUNT}\s*(?:of\s+)?(.+?)\s*$", re.IGNORECASE)
_TRAILING = re.compile(rf"^\s*(.+?)\s*[-:,]?\s*{_AMOUNT}\s*$", re.IGNORECASE)
MAX_TYPED = 30
MAX_NAMED = 5


@dataclass(frozen=True)
class Source:
    id: str
    region: str = "US"
    label: str = LABEL


@dataclass(frozen=True)
class Food:
    key: str
    fdc_id: int
    names: tuple[str, ...]
    per100: Mapping[str, float | None]
    source: str = USDA
    all: Mapping[int, float] = field(default_factory=dict)  # every nutrient, per 100 g


@dataclass(frozen=True)
class DishNutrition:
    installed: bool
    totals: Mapping[str, float] = field(default_factory=dict)
    matched: int = 0
    unmatched: tuple[str, ...] = ()
    grams: int = 0
    full: Mapping[int, float] = field(default_factory=dict)  # every nutrient of the found ones
    labels: tuple[str, ...] = ()  # the label of each source used


def _value(v: object) -> float | None:
    ok = isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)
    return float(v) if ok and 0 <= v < MAX_VALUE else None  # type: ignore[operator, arg-type]


def _all(raw: object) -> dict[int, float]:
    out: dict[int, float] = {}
    for pair in raw if isinstance(raw, list) else ():
        if isinstance(pair, list) and len(pair) == 2 and isinstance(pair[0], int):
            if (v := _value(pair[1])) is not None:
                out[pair[0]] = v
    return out


def _food(raw: object, default_source: str) -> Food | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("key"), str):
        return None
    got = raw.get("per100g")
    per: dict[str, object] = got if isinstance(got, dict) else {}
    values = {n: _value(per.get(n)) for n in NUTRIENTS}
    names = tuple(str(x) for x in raw.get("names") or () if isinstance(x, str))
    fid = raw.get("fdc_id")
    src = raw.get("source")
    return Food(
        raw["key"],
        fid if isinstance(fid, int) and not isinstance(fid, bool) else 0,
        (raw["key"], *names),
        values,
        src if isinstance(src, str) and src else default_source,
        _all(raw.get("all")),
    )


def _sources(raw: object) -> dict[str, Source]:
    out: dict[str, Source] = {}
    for sid, s in raw.items() if isinstance(raw, dict) else ():
        if isinstance(sid, str) and isinstance(s, dict):
            region = s.get("region") if isinstance(s.get("region"), str) else "US"
            label = s.get("label") if isinstance(s.get("label"), str) else LABEL
            out[sid] = Source(sid, str(region)[:8], str(label)[:200])
    return out


def _nutrient_names(raw: object) -> dict[int, tuple[str, str]]:
    out: dict[int, tuple[str, str]] = {}
    for k, v in raw.items() if isinstance(raw, dict) else ():
        if isinstance(k, str) and k.isdigit() and isinstance(v, list) and len(v) == 2:
            name, unit = str(v[0])[:80], str(v[1])[:12]
            out[int(k)] = (name, UNITS.get(unit.upper(), unit))
    return out


class Nutrition:
    def __init__(
        self,
        foods: Sequence[Food],
        *,
        installed: bool,
        sources: Mapping[str, Source] | None = None,
        nutrients: Mapping[int, tuple[str, str]] | None = None,
    ) -> None:
        self.installed = installed and bool(foods)
        self.sources: dict[str, Source] = {USDA: Source(USDA), **(sources or {})}
        self.nutrients: dict[int, tuple[str, str]] = dict(nutrients or {})
        self._by_name: dict[str, list[Food]] = {}
        for f in foods:
            for name in dict.fromkeys(norm_key(n) for n in f.names):
                self._by_name.setdefault(name, []).append(f)

    @classmethod
    def load(cls, *paths: Traversable) -> Nutrition:
        """The data files (default: the USDA subset, then any `nutrition_*.json` beside it, read
        once a process and shared: nothing changes it); a missing, oversized or broken file is
        left out, so none at all reads as not installed."""
        return cls.read(*paths) if paths else _bundled_once()

    @classmethod
    def read(cls, *paths: Traversable) -> Nutrition:
        foods: list[Food] = []
        sources: dict[str, Source] = {}
        names: dict[int, tuple[str, str]] = {}
        installed = False
        for path in paths:
            raw = _read(path)
            if raw is None or raw.get("installed") is not True:
                continue
            got = _sources(raw.get("sources"))
            default = next(iter(got), USDA)
            more = [_food(x, default) for x in (raw.get("foods") or [])[:MAX_FOODS]]
            foods += [f for f in more if f is not None]
            sources.update(got)
            names.update(_nutrient_names(raw.get("nutrients")))
            installed = True
        return cls(foods, installed=installed, sources=sources, nutrients=names)

    def _source(self, food: Food) -> Source:
        return self.sources.get(food.source, Source(food.source))

    def region_of(self, food: Food) -> str:
        return self._source(food).region

    def find(self, name: str) -> Food | None:
        """The food by one of its names: a source marked "IN" first, then USDA's."""
        found = self._by_name.get(norm_key(name)) or []
        indian = [f for f in found if self.region_of(f) == "IN"]
        return (indian or found or [None])[0]

    def dish(self, ingredients: Sequence[Ingredient]) -> DishNutrition:
        if not self.installed:
            return DishNutrition(installed=False)
        totals = dict.fromkeys(NUTRIENTS, 0.0)
        full: dict[int, float] = {}
        unmatched: list[str] = []
        used: list[Food] = []
        for ing in ingredients:
            food = self.find(ing.name)
            if food is None:
                unmatched.append(ing.name)
                continue
            used.append(food)
            for n in NUTRIENTS:
                totals[n] += (food.per100.get(n) or 0.0) * ing.grams / 100
            for nid, v in food.all.items():
                full[nid] = full.get(nid, 0.0) + v * ing.grams / 100
        labels = tuple(
            dict.fromkeys(self.sources.get(f.source, Source(f.source)).label for f in used)
        )
        matched, grams = len(used), sum(i.grams for i in ingredients)
        return DishNutrition(
            True, totals, matched, tuple(unmatched), grams, full, labels or (LABEL,)
        )

    def panel(self, d: DishNutrition) -> list[tuple[str, str]]:
        """Every nutrient of the dish, in the data's order: (name, "amount unit")."""
        out: list[tuple[str, str]] = []
        order = list(self.nutrients) + sorted(set(d.full) - set(self.nutrients))
        for nid in order:
            if nid in d.full:
                name, unit = self.nutrients.get(nid, (f"Nutrient {nid}", ""))
                out.append((name, f"{_num(d.full[nid])} {unit}".strip()))
        return out


@functools.cache
def _bundled_once() -> Nutrition:
    return Nutrition.read(*_bundled())


def _bundled() -> list[Traversable]:
    extra: list[Traversable] = []
    try:
        extra = sorted(
            (p for p in DATA_DIR.iterdir() if EXTRA_GLOB.match(p.name)), key=lambda p: p.name
        )
    except OSError as exc:
        log.warning("nutrition data folder unreadable", extra={"error": type(exc).__name__})
    return [DATA, *extra]


def _read(path: Traversable) -> dict[str, Any] | None:
    try:
        with path.open("rb") as f:
            blob = f.read(MAX_FILE_BYTES + 1)
        if len(blob) > MAX_FILE_BYTES:
            raise ValueError("too big")
        raw = json.loads(blob.decode("utf-8"))
        return raw if isinstance(raw, dict) else None
    except (OSError, ValueError) as exc:
        log.warning("nutrition data unreadable", extra={"error": type(exc).__name__})
        return None


def _num(v: float) -> str:
    if v >= 100:
        return f"{round(v):,}"
    if v >= 10:
        return f"{v:.0f}"
    return f"{v:.1f}" if v >= 1 else f"{v:.2f}".rstrip("0").rstrip(".") or "0"


def _labels(d: DishNutrition) -> str:
    return " ".join(d.labels or (LABEL,))


def key_line(d: DishNutrition) -> str:
    """The six key values: "About 902 kcal, 25 g protein, ... 18 mg sodium"."""
    t = d.totals
    return (
        f"About {round(t['kcal'])} kcal, {round(t['protein_g'])} g protein, "
        f"{round(t['fat_g'])} g fat, {round(t['carb_g'])} g carbohydrate, "
        f"{round(t['fibre_g'])} g fibre, {round(t['sodium_mg'])} mg sodium"
    )


def describe(d: DishNutrition) -> str:
    """The six key values in one fixed-template line, with the honest label and attribution."""
    if not d.installed:
        return NOT_INSTALLED
    if d.matched == 0:
        return f"None of those ingredients is in the nutrition data, Sir ({SOURCE_LINE})."
    tail = f"Nutrient values: {SOURCE_LINE}; a rough guide."
    return f"{key_line(d)}{_partial(d)}. {_labels(d)} {tail}"


def describe_full(d: DishNutrition, n: Nutrition) -> str:
    """Every nutrient (on request): "Full nutrition, about: Water 120 g; Energy 902 kcal; ..."."""
    if not d.installed or d.matched == 0:
        return describe(d)
    values = "; ".join(f"{name} {amount}" for name, amount in n.panel(d))
    return f"Full nutrition, about: {values}{_partial(d)}. {_labels(d)} ({SOURCE_LINE})."


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
    "LABEL",
    "NOT_INSTALLED",
    "NUTRIENTS",
    "USDA",
    "DishNutrition",
    "Food",
    "Nutrition",
    "Source",
    "describe",
    "describe_full",
    "key_line",
    "parse_ingredients",
]
