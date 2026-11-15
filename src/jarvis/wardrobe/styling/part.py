# src/jarvis/wardrobe/styling/part.py
"""R13 Part C's one join (docs/plans/r13-wardrobe.md "Part split"): styling.

Styling (STY-01-17, LND-16, OPS-04).

I0 stub: `build` answers "not built yet". Part C fills it: `build(ctx: WardrobeContext) ->
WardrobePart("styling", ...)` with only its own tools, jobs, services and data
(`jarvis.wardrobe.ports`); `api/r13_wiring.py` leaves out a part that breaks the contract.
"""

from __future__ import annotations

from jarvis.wardrobe.ports import NOT_BUILT, WardrobeContext, WardrobePart


def build(ctx: WardrobeContext) -> WardrobePart:
    return WardrobePart("styling", ready=NOT_BUILT)


__all__ = ["build"]


def build_with(ctx: WardrobeContext, *, fetcher: object = None) -> WardrobePart:
    return build(ctx)
