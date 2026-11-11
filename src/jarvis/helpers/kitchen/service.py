# src/jarvis/helpers/kitchen/service.py
"""The kitchen's one service (docs/plans/r11-free-helpers.md D15): what the tools (chat, voice,
Telegram, No-AI) and the Kitchen tab's routes both call. Every answer is JARVIS's own fixed
template around his own words; a kitchen that is off (no keyring) or can't be read says so in
plain words (`unavailable`). Changes run in one store transaction each (`pantry.*` are pure).
A round that read other people's words can't change his diet (D20: a diet mistake offends).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import ValidationError

from jarvis.helpers.kitchen import pantry as ops
from jarvis.helpers.kitchen.diet import allows
from jarvis.helpers.kitchen.models import (
    DIETS,
    OIL_WORDS,
    SPICE_WORDS,
    Ingredient,
    Kitchen,
    Recipe,
    plain,
)
from jarvis.helpers.kitchen.nutrition import (
    CREDIT,
    LABEL,
    DishNutrition,
    Nutrition,
    describe,
    describe_full,
    key_line,
    parse_ingredients,
)
from jarvis.helpers.kitchen.recipes import DIET_SHORT, RecipeService
from jarvis.helpers.kitchen.spend import GrocerySpendJob, SpendService
from jarvis.helpers.kitchen.store import KitchenOff, KitchenStore, KitchenUnavailable

T = TypeVar("T")
DIET_ALIASES = {
    "veg": "veg", "vegetarian": "veg", "egg": "egg", "eggetarian": "egg",
    "nonveg": "nonveg", "non-veg": "nonveg", "non veg": "nonveg", "non-vegetarian": "nonveg",
}  # fmt: skip
TAINTED_DIET = "Change your diet yourself in Helpers, Kitchen, Sir: I won't take it from a message."
EMPTY_PANTRY = "Your pantry is empty, Sir. Say 'add rice and dal to my pantry'."
NOT_VEG = "That recipe has meat, fish or egg in it, so it can't be saved as {diet}, Sir."
DEFAULT_MINUTES = 30


def diet_of(value: object) -> str | None:
    if value is None or value == "":
        return None
    found = DIET_ALIASES.get(" ".join(str(value).casefold().split()))
    if found is None:
        raise ValueError("diet is veg, egg or nonveg")
    return found


def _steps(value: object) -> tuple[str, ...]:
    if isinstance(value, list | tuple):
        return tuple(str(s) for s in value if str(s).strip())
    parts = [p.strip() for p in str(value or "").replace("\n", ";").split(";")]
    return tuple(p for p in parts if p)


def _ingredients(value: object) -> tuple[Ingredient, ...]:
    if not isinstance(value, list | tuple):
        return parse_ingredients(str(value or ""))
    try:
        return tuple(
            Ingredient.model_validate({"name": i.get("name"), "grams": i.get("grams")})
            for i in value
            if isinstance(i, dict)
        )
    except ValidationError as exc:
        raise plain(exc) from None


def _minutes(value: object) -> int:
    if value is None or value == "":
        return DEFAULT_MINUTES
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    text = str(value).strip()
    if isinstance(value, bool) or not (text.isascii() and text.isdigit()):
        raise ValueError("minutes is a whole number from 1 to 600")
    return int(text)


def recipe_from(args: Mapping[str, Any], rid: str) -> Recipe:
    """A recipe from tool or route arguments (ValueError in plain words, never the input)."""
    data = {
        "id": rid,
        "title": args.get("title"),
        "cuisine": args.get("cuisine") or "",
        "diet": diet_of(args.get("diet")) or "veg",
        "minutes": _minutes(args.get("minutes")),
        "ingredients": _ingredients(args.get("ingredients")),
        "steps": _steps(args.get("steps")),
    }
    try:
        return Recipe.model_validate(data)
    except ValidationError as exc:
        raise plain(exc) from None


def _list(names: list[str]) -> str:
    return ", ".join(names)


@dataclass(frozen=True)
class KitchenService:
    store: KitchenStore
    recipes: RecipeService
    spend: SpendService
    nutrition: Nutrition
    job: GrocerySpendJob | None = None
    calendar: bool = False

    async def _guard(self, work: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
        try:
            return await work()
        except (KitchenOff, KitchenUnavailable) as exc:
            return {"message": str(exc), "unavailable": True}

    async def _change(self, uid: str, fn: Callable[[Kitchen], tuple[Kitchen, T]]) -> T:
        return await self.store.update(uid, fn)

    async def pantry(self, uid: str) -> dict[str, Any]:
        async def work() -> dict[str, Any]:
            items = list((await self.store.load(uid)).pantry)
            if not items:
                return {"pantry": [], "message": EMPTY_PANTRY}
            return {"pantry": items, "message": f"In your pantry, Sir: {_list(items)}."}

        return await self._guard(work)

    async def add(self, uid: str, items: object) -> dict[str, Any]:
        names = ops.split_items(items)

        async def work() -> dict[str, Any]:
            added, already = await self._change(uid, lambda k: _pair(ops.add_items(k, names)))
            bits = [f"Added to your pantry: {_list(added)}." if added else "Nothing new to add."]
            if already:
                bits.append(f"Already there: {_list(already)}.")
            return {"added": added, "already": already, "message": " ".join(bits)}

        return await self._guard(work)

    async def remove(self, uid: str, items: object) -> dict[str, Any]:
        names = ops.split_items(items)

        async def work() -> dict[str, Any]:
            removed, missing = await self._change(uid, lambda k: _pair(ops.remove_items(k, names)))
            out = (
                f"Taken out of your pantry: {_list(removed)}." if removed else "Nothing taken out."
            )
            bits = [out]
            if missing:
                bits.append(f"Not in it: {_list(missing)}.")
            return {"removed": removed, "missing": missing, "message": " ".join(bits)}

        return await self._guard(work)

    async def settings(self, uid: str, args: Mapping[str, Any], *, tainted: bool) -> dict[str, Any]:
        changes = _prefs_changes(args)
        if "diet" in changes and tainted:
            return {"message": TAINTED_DIET, "refused": True}

        async def work() -> dict[str, Any]:
            await self.store.change(uid, lambda k: ops.set_prefs(k, changes))
            p = (await self.store.load(uid)).prefs
            cuisines = f", cuisines {_list(list(p.cuisines))}" if p.cuisines else ""
            return {
                "message": f"Your kitchen is set, Sir: {DIET_SHORT[p.diet]}, "
                f"{SPICE_WORDS[p.spice]}, {OIL_WORDS[p.oil]}{cuisines}."
            }

        return await self._guard(work)

    async def save_recipe(
        self, uid: str, args: Mapping[str, Any], rid: str | None = None
    ) -> dict[str, Any]:
        recipe = recipe_from(args, rid or uuid.uuid4().hex[:12])
        if not allows(recipe, recipe.diet):
            raise ValueError(NOT_VEG.format(diet=DIET_SHORT[recipe.diet]))

        async def work() -> dict[str, Any]:
            replaced = await self._change(uid, lambda k: ops.save_recipe(k, recipe))
            verb = "Updated" if replaced else "Saved"
            return {"id": recipe.id, "message": f"{verb} in your recipes, Sir: {recipe.title}."}

        return await self._guard(work)

    async def list_recipes(self, uid: str) -> dict[str, Any]:
        async def work() -> dict[str, Any]:
            rs = (await self.store.load(uid)).recipes
            if not rs:
                return {"recipes": [], "message": "You have no saved recipes yet, Sir."}
            bits = [f"{r.title} ({r.minutes} min, {DIET_SHORT[r.diet]})" for r in rs]
            message = f"Your saved recipes, Sir: {_list(bits)}."
            return {"recipes": [r.title for r in rs], "message": message}

        return await self._guard(work)

    async def forget_recipe(self, uid: str, rid: str) -> bool:
        return await self._change(uid, lambda k: ops.forget_recipe(k, rid))

    def _said(self, d: DishNutrition, detail: object) -> dict[str, Any]:
        """The six key values by default; every nutrient when he asks ("full nutrition", I1)."""
        n = self.nutrition
        if detail != "full":
            return {"message": describe(d)}
        values = [{"name": k, "amount": v} for k, v in n.panel(d)] if d.installed else []
        return {"message": describe_full(d, n), "values": values}

    async def nutrition_of(self, uid: str, args: Mapping[str, Any]) -> dict[str, Any]:
        detail = args.get("detail")
        if args.get("ingredients"):
            items = _ingredients(args.get("ingredients"))
            return self._said(self.nutrition.dish(items), detail)

        async def work() -> dict[str, Any]:
            name = str(args.get("recipe") or "")
            found = ops.find_recipe(await self.store.load(uid), name)
            if found is None and (food := self.nutrition.find(name)) is not None:
                out = self._said(self.nutrition.dish((Ingredient(name=name, grams=100),)), detail)
                return {**out, "message": f"Per 100 g of raw {food.key}: {out['message']}"}
            if found is None:
                return {"message": "I can't find that in your saved recipes, Sir. Give the grams, "
                        "such as '200 g rice, 100 g dal'."}  # fmt: skip
            out = self._said(self.nutrition.dish(found.ingredients), detail)
            return {**out, "message": f"{found.title}: {out['message']}"}

        return await self._guard(work)

    async def set_blocks(self, uid: str, plan: Mapping[str, Any]) -> None:
        await self.store.change(uid, lambda k: ops.set_blocks(k, plan))

    def _row(self, r: Recipe) -> dict[str, Any]:
        n = self.nutrition
        d = n.dish(r.ingredients) if n.installed else None
        return {
            "id": r.id,
            "title": r.title,
            "cuisine": r.cuisine,
            "diet": r.diet,
            "minutes": r.minutes,
            "ingredients": len(r.ingredients),
            "nutrition": key_line(d) if d is not None and d.matched else None,
            # I1: every nutrient, for the tab's expandable list ([name, "amount unit"])
            "nutrition_full": [list(x) for x in n.panel(d)] if d is not None else [],
        }

    async def view(self, uid: str) -> dict[str, Any]:
        """The Kitchen tab: everything it shows, in one answer."""
        k = await self.store.load(uid)
        scan = await self.spend.store.scan(uid)
        recipes = [self._row(r) for r in k.recipes]
        return {
            "sealed": True,
            "pantry": list(k.pantry),
            "prefs": k.prefs.model_dump(mode="json"),
            "recipes": recipes,
            "blocks": k.blocks.model_dump(mode="json"),
            "spend": {
                "on": scan.on,
                "can_scan": self.spend.can_scan,
                "last_at": scan.last_at,
                "months": await self.spend.totals(uid) if scan.on else [],
            },  # fmt: skip
            # the honest label and the credit, drawn as they are by the Kitchen tab (review L5)
            "nutrition": {"installed": self.nutrition.installed, "label": LABEL, "credit": CREDIT},
            "calendar": self.calendar,
            "words": {"diets": list(DIETS), "spice": list(SPICE_WORDS), "oil": list(OIL_WORDS)},
        }


def _pair(t: tuple[Kitchen, list[str], list[str]]) -> tuple[Kitchen, tuple[list[str], list[str]]]:
    return t[0], (t[1], t[2])


def _prefs_changes(args: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if (d := diet_of(args.get("diet"))) is not None:
        out["diet"] = d
    for key in ("spice", "oil"):
        v = args.get(key)
        if v is not None and v != "":
            if isinstance(v, bool) or not str(v).strip().isdigit():
                raise ValueError(f"{key} is a whole number")
            out[key] = int(str(v).strip())
    if args.get("cuisines") is not None:
        c = args["cuisines"]
        out["cuisines"] = tuple(c) if isinstance(c, list | tuple) else tuple(ops.split_items(c))
    if args.get("note") is not None:
        out["note"] = str(args["note"])
    return out


__all__ = ["DIET_ALIASES", "TAINTED_DIET", "KitchenService", "diet_of", "recipe_from"]
