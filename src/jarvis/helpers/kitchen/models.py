# src/jarvis/helpers/kitchen/models.py
"""The kitchen's data (docs/plans/r11-free-helpers.md data model, D15). Frozen, extra fields
refused, every text one clean line of bounded length.

- `Kitchen` (sealed in `{prefix}kitchen/{uid}`, purpose `kitchen`): the pantry (names only, at most
  200), his tastes (`Prefs`: diet, spice 0-3, oil 0-2, cuisines, a short note), saved recipes (at
  most 100, ingredients with grams) and the cooking / washing-up block plan.
- `Order` / `SpendMonth` (sealed in `{prefix}spend/{uid}_{yyyymm}`, purpose `spend`): per order
  the merchant (from the fixed list), the day, the amount in paise and a keyed hash; nothing else.
- `ScanState` (`{prefix}spend_scan/{uid}`, not sealed): whether he switched receipts on, the last
  scan, keyed hashes of the mails already read (at most 500).

No text may hold a run of 12 or more digits (a card or account number never gets in).
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from jarvis.tools.card import one_line

Diet = Literal["veg", "egg", "nonveg"]
DIETS: tuple[Diet, ...] = ("veg", "egg", "nonveg")
DIET_WORDS = {
    "veg": "vegetarian (no meat, fish or egg)",
    "egg": "vegetarian with eggs (no meat or fish)",
    "nonveg": "non-vegetarian",
}
SPICE_WORDS = ("not spicy", "mild", "medium", "hot")
OIL_WORDS = ("very little oil", "normal oil", "rich")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MAX_PANTRY = 200
MAX_RECIPES = 100
MAX_CUISINES = 6
MAX_INGREDIENTS = 30
MAX_STEPS = 10
NAME_MAX = 60
CUISINE_MAX = 30
TITLE_MAX = 80
STEP_MAX = 300
NOTE_MAX = 200
GRAMS_MAX = 5_000
MINUTES_MAX = 600
MAX_ORDER_PAISE = 10_000_000  # ₹1,00,000: a grocery order above this is a misread
MAX_ORDERS_A_MONTH = 400
MAX_SEEN = 500
_LONG_NUMBER = re.compile(r"\d{12,}")
_HHMM = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_FROZEN = ConfigDict(extra="forbid", frozen=True)


def clean(value: object, limit: int, *, empty_ok: bool = False) -> str:
    """One line of plain text of at most `limit` characters; never a long number."""
    if not isinstance(value, str):
        raise ValueError("must be text")
    text = one_line(value, limit + 1)
    if len(text) > limit:
        raise ValueError(f"must be at most {limit} characters")
    if not text and not empty_ok:
        raise ValueError("must not be empty")
    if _LONG_NUMBER.search(text.replace(" ", "").replace("-", "")):
        raise ValueError("must not hold a card or account number")
    return text


def _name(v: str) -> str:
    return clean(v, NAME_MAX)


Name = Annotated[str, AfterValidator(_name)]


class Prefs(BaseModel):
    model_config = _FROZEN
    diet: Diet = "veg"  # the safe default: a veg kitchen is never offended
    spice: int = Field(default=1, ge=0, le=3)
    oil: int = Field(default=1, ge=0, le=2)
    cuisines: tuple[str, ...] = Field(default=(), max_length=MAX_CUISINES)
    note: str = ""

    @field_validator("cuisines")
    @classmethod
    def _cuisines(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(clean(c, CUISINE_MAX) for c in v))

    @field_validator("note")
    @classmethod
    def _note(cls, v: str) -> str:
        return clean(v, NOTE_MAX, empty_ok=True)


class Ingredient(BaseModel):
    model_config = _FROZEN
    name: Name
    grams: int = Field(ge=1, le=GRAMS_MAX)


class Recipe(BaseModel):
    model_config = _FROZEN
    id: str = Field(pattern=r"^[a-z0-9]{8,32}$")
    title: str
    cuisine: str = ""
    diet: Diet
    minutes: int = Field(ge=1, le=MINUTES_MAX)
    ingredients: tuple[Ingredient, ...] = Field(min_length=1, max_length=MAX_INGREDIENTS)
    steps: tuple[str, ...] = Field(min_length=1, max_length=MAX_STEPS)

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        return clean(v, TITLE_MAX)

    @field_validator("cuisine")
    @classmethod
    def _cuisine(cls, v: str) -> str:
        return clean(v, CUISINE_MAX, empty_ok=True)

    @field_validator("steps")
    @classmethod
    def _steps(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(clean(s, STEP_MAX) for s in v)


def _hhmm(v: str) -> str:
    if not _HHMM.match(v):
        raise ValueError("a time must read HH:MM, such as 19:00")
    return v


class BlockPlan(BaseModel):
    """Cooking and washing-up times he likes (the card always asks before the calendar)."""

    model_config = _FROZEN
    cooking_at: Annotated[str, AfterValidator(_hhmm)] = "19:00"
    cooking_minutes: int = Field(default=45, ge=10, le=180)
    washing_at: Annotated[str, AfterValidator(_hhmm)] = "20:30"
    washing_minutes: int = Field(default=15, ge=5, le=90)
    days: tuple[str, ...] = ()  # () = every day

    @field_validator("days")
    @classmethod
    def _days(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if any(d not in DAYS for d in v):
            raise ValueError("days are mon, tue, wed, thu, fri, sat or sun")
        return tuple(d for d in DAYS if d in v)


class Kitchen(BaseModel):
    model_config = _FROZEN
    pantry: tuple[Name, ...] = Field(default=(), max_length=MAX_PANTRY)
    prefs: Prefs = Field(default_factory=Prefs)
    recipes: tuple[Recipe, ...] = Field(default=(), max_length=MAX_RECIPES)
    blocks: BlockPlan = Field(default_factory=BlockPlan)


class Order(BaseModel):
    model_config = _FROZEN
    key: str = Field(pattern=r"^[0-9a-f]{16,64}$")
    merchant: str = Field(min_length=1, max_length=40)
    day: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    paise: int = Field(ge=1, le=MAX_ORDER_PAISE)


class SpendMonth(BaseModel):
    model_config = _FROZEN
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    orders: tuple[Order, ...] = Field(default=(), max_length=MAX_ORDERS_A_MONTH)

    @property
    def total_paise(self) -> int:
        return sum(o.paise for o in self.orders)

    def by_merchant(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for o in self.orders:
            out[o.merchant] = out.get(o.merchant, 0) + o.paise
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))


class ScanState(BaseModel):
    model_config = _FROZEN
    on: bool = False
    last_at: str | None = None
    seen: tuple[str, ...] = Field(default=(), max_length=MAX_SEEN)
    rev: int = Field(default=0, ge=0)


__all__ = [
    "DAYS",
    "DIETS",
    "DIET_WORDS",
    "MAX_ORDER_PAISE",
    "MAX_PANTRY",
    "MAX_RECIPES",
    "MAX_SEEN",
    "OIL_WORDS",
    "SPICE_WORDS",
    "BlockPlan",
    "Diet",
    "Ingredient",
    "Kitchen",
    "Order",
    "Prefs",
    "Recipe",
    "ScanState",
    "SpendMonth",
    "clean",
]
