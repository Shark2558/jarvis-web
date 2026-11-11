# src/jarvis/helpers/kitchen/part.py
"""R11 Part D's plug-in (docs/plans/r11-free-helpers.md D2, D15): `build(ctx)` returns everything
the app wires for the kitchen (items 13-16), using only what `ctx` hands it:

- tools: `pantry_*`, `kitchen_settings`, `recipe_*`, `nutrition_of`, `spend_month` (the Kitchen
  row) and, with Google linked, `calendar_kitchen_blocks` (the calendar row, always a card);
- daily job `grocery_spend` (with a keyring and Google; it obeys his permission rows);
- privacy rows `helpers_kitchen` and `helpers_spend`; the brief's grocery line on the 1st;
- the No-AI phrases; the services its routes read (`api/helpers_kitchen.py`);
- paused: grocery spend, when his Email or Kitchen row stops the receipts' read.
Sealed data needs `ctx.keyring` (purposes `kitchen`, `spend`); without it the kitchen says it is
off and keeps nothing. Recipes use `ctx.brains` by tier and `ctx.billing`; never the alerts (the
kitchen sends none).
"""

from __future__ import annotations

from jarvis.helpers.kitchen.blocks import blocks_tool
from jarvis.helpers.kitchen.brief import KitchenBrief
from jarvis.helpers.kitchen.nutrition import Nutrition
from jarvis.helpers.kitchen.phrases import PHRASES
from jarvis.helpers.kitchen.privacy import kitchen_privacy, spend_privacy
from jarvis.helpers.kitchen.recipes import RecipeService
from jarvis.helpers.kitchen.service import KitchenService
from jarvis.helpers.kitchen.spend import GrocerySpendJob, SpendService, spend_pause
from jarvis.helpers.kitchen.store import KitchenStore, SpendStore
from jarvis.helpers.kitchen.tools import kitchen_tools
from jarvis.helpers.ports import HelperContext, HelperPart

SERVICE = "kitchen"


def _ready(ctx: HelperContext, nutrition: Nutrition) -> str:
    if ctx.keyring is None:
        return "off: JARVIS has no token key, so the kitchen can't keep anything sealed"
    notes = []
    if ctx.google is None:
        notes.append("Google isn't linked: no receipts or calendar blocks")
    if not nutrition.installed:
        notes.append("nutrition data not installed")
    return "ready" + (f" ({'; '.join(notes)})" if notes else "")


def build(ctx: HelperContext) -> HelperPart:
    nutrition = Nutrition.load()
    kstore = KitchenStore(ctx.docs, ctx.keyring, prefix=ctx.prefix, now=ctx.now)
    sstore = SpendStore(ctx.docs, ctx.keyring, prefix=ctx.prefix, now=ctx.now, tz=ctx.tz)
    recipes = RecipeService(
        kstore, brains=ctx.brains, billing=ctx.billing, mode=ctx.brain_mode, nutrition=nutrition
    )
    spend = SpendService(sstore, google=ctx.google, now=ctx.now, tz=ctx.tz)
    job = GrocerySpendJob(spend, owners=ctx.owners, reads=ctx.reads)
    svc = KitchenService(
        kstore, recipes, spend, nutrition, job=job if spend.can_scan else None,
        calendar=ctx.google is not None,
    )  # fmt: skip
    tools = kitchen_tools(svc)
    if ctx.google is not None:
        tools.append(blocks_tool(ctx.google, tz=ctx.tz, now=ctx.now))
    return HelperPart(
        name="kitchen",
        tools=tuple(tools),
        daily_jobs=(job,) if spend.can_scan else (),
        privacy=(kitchen_privacy(kstore), spend_privacy(sstore)),
        brief=(KitchenBrief(spend),),
        phrases=PHRASES,
        services={SERVICE: svc},
        ready=_ready(ctx, nutrition),
        paused=(spend_pause(spend, ctx.reads),) if spend.can_scan else (),
    )


__all__ = ["SERVICE", "build"]
