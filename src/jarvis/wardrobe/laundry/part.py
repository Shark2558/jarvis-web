# src/jarvis/wardrobe/laundry/part.py
"""R13 Part B's one join (docs/plans/r13-wardrobe.md "Part split"): laundry.

Laundry (LND-01-08, LND-10-15, OPS-02).

I0 stub: `build` answers "not built yet". Part B fills it: `build(ctx: WardrobeContext) ->
WardrobePart("laundry", ...)` with only its own tools, jobs, services and data
(`jarvis.wardrobe.ports`); `api/r13_wiring.py` leaves out a part that breaks the contract.
"""

from __future__ import annotations

from jarvis.wardrobe.ports import NOT_BUILT, WardrobeContext, WardrobePart


def build(ctx: WardrobeContext) -> WardrobePart:
    return WardrobePart("laundry", ready=NOT_BUILT)


__all__ = ["build"]
