# src/jarvis/helpers/kitchen/tools.py
"""The kitchen's tools (docs/plans/r11-free-helpers.md D15, D16): every one in the Kitchen
permission row (`pantry_*`, `recipe_*`, `nutrition_*`, `spend_*`, `kitchen_*`) at R1 or R2, so
every call passes the gateway (policy, audit, cards). `calendar_kitchen_blocks` (blocks.py) is
the one in the calendar row. Arguments arrive from the model (typed) or from the No-AI phrases
(strings), so each accepts both. Results carry a fixed-template `message` (the No-AI reply).
Activity shows fixed words for every one (`activity_words`): no pantry note, recipe or amount
reaches the 7-day Activity log.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

from jarvis.core.guardrails import ActionRisk
from jarvis.helpers.kitchen.recipes import parse_request
from jarvis.helpers.kitchen.service import KitchenService, diet_of
from jarvis.tools.base import Tool
from jarvis.tools.context import require_tool_context
from jarvis.tools.taint import content_tainted

R1, R2 = ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE
AGENT = "helpers"
_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_TEXT = {"type": "string", "maxLength": 2000}
_INGREDIENTS = {
    "type": "string",
    "maxLength": 2000,
    "description": "Ingredients with grams, e.g. '200 g rice, 100 g toor dal, 80 g onion'",
}
_STEPS = {"type": "string", "maxLength": 4000, "description": "The steps, one a line"}
_DIET = {"type": "string", "enum": ["veg", "egg", "nonveg"]}
_PREFS = {
    "diet": _DIET,
    "spice": {"type": "integer", "minimum": 0, "maximum": 3},
    "oil": {"type": "integer", "minimum": 0, "maximum": 2},
    "cuisines": {"type": "string", "maxLength": 200},
    "note": {"type": "string", "maxLength": 200},
}
_SUGGEST = {
    "diet": _DIET,
    "cuisine": {"type": "string", "maxLength": 30},
    "with": {"type": "string", "maxLength": 200},
}
_SAVE = {
    "title": {"type": "string", "maxLength": 80},
    "cuisine": {"type": "string", "maxLength": 30},
    "diet": _DIET,
    "minutes": {"type": "integer", "minimum": 1, "maximum": 600},
    "ingredients": _INGREDIENTS,
    "steps": _STEPS,
}
Run = Callable[[str, dict[str, Any]], Awaitable[Any]]


def _uid() -> str:
    return require_tool_context().user_id


def _wrap(fn: Run) -> Callable[[dict[str, Any]], Awaitable[Any]]:
    async def run(a: dict[str, Any]) -> Any:
        return await fn(_uid(), a)

    return run


def _check_month(a: dict[str, Any]) -> None:
    m = a.get("month")
    if m not in (None, "") and not _MONTH.match(str(m)):
        raise ValueError("month must read YYYY-MM, such as 2026-11")


def _check_suggest(a: dict[str, Any]) -> None:
    parse_request(a)


def _check_settings(a: dict[str, Any]) -> None:
    diet_of(a.get("diet"))


def _schema(props: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        out["required"] = list(required)
    return out


def _tool(
    name: str,
    desc: str,
    props: dict[str, Any],
    risk: ActionRisk,
    run: Run,
    words: str,
    *,
    required: tuple[str, ...] = (),
    check: Callable[[dict[str, Any]], None] | None = None,
) -> Tool:
    return Tool(
        name,
        desc,
        _schema(props, required),
        risk,
        _wrap(run),
        agent=AGENT,
        check=check,
        activity_words=words,
    )


def _pantry_tools(svc: KitchenService) -> list[Tool]:
    """The pantry and his tastes."""
    items = {"items": {**_TEXT, "description": "Comma-separated names, e.g. 'rice, toor dal'"}}

    async def settings(uid: str, a: dict[str, Any]) -> Any:
        # their words this round, or a card proposed after reading them (D8 `outside`)
        tainted = content_tainted() or require_tool_context().outside
        return await svc.settings(uid, a, tainted=tainted)

    return [
        _tool(
            "pantry_list",
            "What is in the owner's pantry (his own list).",
            {},
            R1,
            lambda uid, a: svc.pantry(uid),
            "Pantry read",
        ),
        _tool(
            "pantry_add",
            "Add items to the owner's pantry (what he has at home).",
            items,
            R2,
            lambda uid, a: svc.add(uid, a.get("items")),
            "Pantry changed",
            required=("items",),
        ),
        _tool(
            "pantry_remove",
            "Take items out of the owner's pantry.",
            items,
            R2,
            lambda uid, a: svc.remove(uid, a.get("items")),
            "Pantry changed",
            required=("items",),
        ),
        _tool(
            "kitchen_settings",
            "Set the owner's kitchen tastes: diet (veg, egg, nonveg), spice 0-3, oil 0-2, "
            "cuisines (comma-separated), a short note. A diet change is refused after reading "
            "other people's content: he changes it himself.",
            _PREFS,
            R2,
            settings,
            "Kitchen settings changed",
            check=_check_settings,
        ),
    ]


def _recipe_tools(svc: KitchenService) -> list[Tool]:
    """Recipe ideas, saved recipes and nutrition."""
    return [
        _tool(
            "recipe_suggest",
            "One recipe idea from what the owner has, for his diet (a code check refuses any "
            "idea that breaks it). Costs like a normal reply; with the AI off it lists his saved "
            "recipes. Optional: diet (only stricter than his), cuisine, with (ingredients to use).",
            _SUGGEST,
            R1,
            svc.recipes.suggest,
            "Recipe idea",
            check=_check_suggest,
        ),
        _tool(
            "recipe_save",
            "Save a recipe in the owner's recipes (title, diet, minutes, ingredients with grams, "
            "steps). One with the same title is replaced.",
            _SAVE,
            R2,
            svc.save_recipe,
            "Recipe saved",
            required=("title", "ingredients", "steps"),
        ),
        _tool(
            "recipe_list",
            "The owner's saved recipes.",
            {},
            R1,
            lambda uid, a: svc.list_recipes(uid),
            "Recipes read",
        ),
        _tool(
            "nutrition_of",
            "Rough nutrition of a dish (USDA FoodData Central, raw ingredients): a saved "
            "recipe's title, or ingredients with grams.",
            {"recipe": {"type": "string", "maxLength": 80}, "ingredients": _INGREDIENTS},
            R1,
            svc.nutrition_of,
            "Nutrition looked up",
        ),
    ]


def _spend_tools(svc: KitchenService) -> list[Tool]:
    """Grocery spend from his receipts."""

    async def spend(uid: str, a: dict[str, Any]) -> Any:
        return await svc.spend.month(uid, a.get("month") or None)

    return [
        _tool(
            "spend_month",
            "The owner's grocery spend for a month (YYYY-MM; default this month), totalled from "
            "his e-mailed grocery receipts.",
            {"month": {"type": "string", "pattern": r"^\d{4}-\d{2}$"}},
            R1,
            spend,
            "Grocery spend read",
            check=_check_month,
        ),
    ]


def kitchen_tools(svc: KitchenService) -> list[Tool]:
    return [*_pantry_tools(svc), *_recipe_tools(svc), *_spend_tools(svc)]


__all__ = ["kitchen_tools"]
