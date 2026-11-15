# src/jarvis/wardrobe/styling/part.py
"""R13 Part C's one join (docs/plans/r13-wardrobe.md "Part split"): styling (STY-01-17, LND-16,
OPS-04).

`build(ctx) -> WardrobePart("styling", ...)`: its five tools (`outfit_*`, `wear_log`), its one
5-minute job (`outfit_clock`: the weather, the calendar, the evening's `outfit_ready`), its
refresh (`services["refresh"]`, the `ChangeObserver` the wiring binds FIRST into A's store; the
routes reach the styling service and the calendar through it: C may offer no other service
name) and its data for D's Privacy rows. The rules file is checked here: one that fails raises,
so the wiring leaves the part out ("setup failed") and the others run. No token key or no
storage: the part is still built, its tools and routes say plainly that outfits are off, and
nothing is written in clear.
"""

from __future__ import annotations

from typing import Any

from jarvis.helpers.house.fetch import Fetcher, HttpFetcher
from jarvis.wardrobe.ports import WardrobeContext, WardrobePart
from jarvis.wardrobe.styling.calendar import CalDoc, Calendar
from jarvis.wardrobe.styling.data import OutfitsData
from jarvis.wardrobe.styling.jobs import OutfitClock
from jarvis.wardrobe.styling.outlook import Outlook, OutlookDoc
from jarvis.wardrobe.styling.plans import StylingDoc
from jarvis.wardrobe.styling.refresh import PlanRefresh
from jarvis.wardrobe.styling.rules import Rules, load_rules
from jarvis.wardrobe.styling.sealed import SealedDoc, Told
from jarvis.wardrobe.styling.service import Styling
from jarvis.wardrobe.styling.texts import OFF_NO_KEY, OFF_NO_STORE
from jarvis.wardrobe.styling.tools import styling_tools

READY = "ready"
READY_WORDS = {OFF_NO_STORE: "off: no storage", OFF_NO_KEY: "off: no token key"}


def _sealed(ctx: WardrobeContext, collection: str, model: Any) -> SealedDoc[Any]:
    return SealedDoc(
        ctx.docs, ctx.keyring, collection=collection, model=model, now=ctx.now,
        prefix=ctx.s.firestore_prefix,
    )  # fmt: skip


def build_with(
    ctx: WardrobeContext, *, fetcher: Fetcher | None = None, rules: Rules | None = None
) -> WardrobePart:
    checked = rules or load_rules()
    weather = _sealed(ctx, "wardrobe_outlook", OutlookDoc)
    outlook = Outlook(ctx, fetcher or HttpFetcher(), weather, checked)
    told = Told(ctx.docs, now=ctx.now, prefix=ctx.s.firestore_prefix)
    styling = Styling(ctx, checked, _sealed(ctx, "wardrobe_plans", StylingDoc), told, outlook)
    calendar = Calendar(ctx, checked, _sealed(ctx, "wardrobe_cal", CalDoc))
    refresh = PlanRefresh(styling, calendar)
    return WardrobePart(
        "styling",
        tools=styling_tools(styling),
        clock_jobs=(OutfitClock(styling, calendar),),
        data=(OutfitsData(styling, calendar),),
        services={"refresh": refresh},
        ready=READY_WORDS.get(styling.off() or "", READY),
    )


def build(ctx: WardrobeContext) -> WardrobePart:
    return build_with(ctx)


__all__ = ["READY", "READY_WORDS", "build", "build_with"]
