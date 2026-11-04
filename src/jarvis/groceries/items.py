# src/jarvis/groceries/items.py
"""Grocery items as Google Tasks titles (R1 D14). Pure.

A title reads "Milk (2 L)": the owner's own words for the name, an optional quantity and unit in
brackets. `parse_title` reads that back (any other title is just a name). Dedupe works on
`norm_key`: NFC, casefold, collapsed spaces, a simple Latin plural strip on the last word and a
small synonym table (curd = yogurt, brinjal = eggplant, ...). Merging adds quantities only when the
units match; otherwise the new quantity replaces the old one and the result says so.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

NAME_MAX = 80
UNIT_MAX = 12
QTY_MAX = Decimal(10_000)

UNIT_ALIASES = {
    "l": "L", "ltr": "L", "ltrs": "L", "litre": "L", "litres": "L", "liter": "L", "liters": "L",
    "ml": "ml", "millilitre": "ml", "milliliter": "ml", "millilitres": "ml", "milliliters": "ml",
    "kg": "kg", "kgs": "kg", "kilo": "kg", "kilos": "kg", "kilogram": "kg", "kilograms": "kg",
    "g": "g", "gm": "g", "gms": "g", "gram": "g", "grams": "g",
    "pc": "pcs", "pcs": "pcs", "piece": "pcs", "pieces": "pcs",
    "pack": "pack", "packs": "pack", "packet": "pack", "packets": "pack",
    "dozen": "dozen", "doz": "dozen",
}  # fmt: skip
SYNONYMS = {
    "curd": "yogurt", "yoghurt": "yogurt", "dahi": "yogurt",
    "brinjal": "eggplant", "aubergine": "eggplant",
    "capsicum": "bell pepper", "lady finger": "okra", "ladyfinger": "okra", "bhindi": "okra",
    "coriander": "cilantro", "coriander leaf": "cilantro", "atta": "wheat flour",
    "maida": "all purpose flour", "chilli": "chili", "chilly": "chili",
}  # fmt: skip
_TITLE = re.compile(
    r"^(?P<name>.*?)\s*\(\s*(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>[A-Za-z. ]{0,12}?)\s*\)\s*$"
)
_UNIT_OK = re.compile(r"[A-Za-z][A-Za-z. ]{0,11}")


@dataclass(frozen=True)
class Item:
    name: str
    qty: Decimal | None = None
    unit: str | None = None


def clean_name(value: str) -> str:
    text = unicodedata.normalize("NFC", " ".join(str(value).split()))
    return text.strip()


def clean_unit(value: str | None) -> str | None:
    if value is None:
        return None
    raw = " ".join(str(value).split()).strip(". ").casefold()
    if not raw:
        return None
    if not _UNIT_OK.fullmatch(raw):
        raise ValueError("unit must be a short word like kg, L, pack")
    return UNIT_ALIASES.get(raw, raw)


def to_qty(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float | str | Decimal):
        raise ValueError("qty must be a number")
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("qty must be a number") from None
    if not d.is_finite() or d <= 0 or d > QTY_MAX:
        raise ValueError("qty must be more than 0 and at most 10000")
    return d.normalize()


def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("oes"):
        return word[:-2]
    if len(word) > 4 and word.endswith(("ches", "shes", "sses", "xes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def norm_key(name: str) -> str:
    """The dedupe key: "Tomatoes", " tomato " and "TOMATO" are one item; so are curd and yogurt."""
    words = unicodedata.normalize("NFC", name).casefold().replace("-", " ").split()
    words = [w.strip(".,;:!?'\"") for w in words]
    words = [w for w in words if w]
    if not words:
        return ""
    words[-1] = _singular(words[-1])
    phrase = " ".join(words)
    return SYNONYMS.get(phrase, phrase)


def fmt_qty(q: Decimal) -> str:
    return format(q.normalize(), "f")


def format_title(item: Item) -> str:
    if item.qty is None:
        return item.name
    unit = f" {item.unit}" if item.unit else ""
    return f"{item.name} ({fmt_qty(item.qty)}{unit})"


def parse_title(title: str) -> Item:
    m = _TITLE.match(" ".join(title.split()))
    if not m or not m.group("name"):
        return Item(clean_name(title))
    try:
        unit = clean_unit(m.group("unit")) if m.group("unit").strip() else None
        return Item(clean_name(m.group("name")), to_qty(m.group("qty")), unit)
    except ValueError:
        return Item(clean_name(title))


Action = Literal["added", "merged", "already_on_list", "replaced"]


def merge(existing: Item, new: Item) -> tuple[Item, Action]:
    """What the list should say after adding `new` to a line that already holds `existing`."""
    if new.qty is None:
        return existing, "already_on_list"
    if existing.qty is None or existing.unit != new.unit:
        return Item(existing.name, new.qty, new.unit), "replaced"
    return Item(existing.name, existing.qty + new.qty, existing.unit), "merged"


__all__ = [
    "NAME_MAX",
    "Action",
    "Item",
    "clean_name",
    "clean_unit",
    "format_title",
    "fmt_qty",
    "merge",
    "norm_key",
    "parse_title",
    "to_qty",
]
