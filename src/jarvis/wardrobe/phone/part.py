# src/jarvis/wardrobe/phone/part.py
"""R13 Part D's one join (docs/plans/r13-wardrobe.md "Part split"): phone.

Phone and panel (OPS-01, the UI of every part, the Privacy rows, the No-AI sentences).

I0 stub: `build` answers "not built yet". Part D fills it: `build(ctx: WardrobeContext) ->
WardrobePart("phone", ...)` with only its own tools, jobs, services and data
(`jarvis.wardrobe.ports`); `api/r13_wiring.py` leaves out a part that breaks the contract.
"""

from __future__ import annotations

from jarvis.wardrobe.ports import NOT_BUILT, WardrobeContext, WardrobePart


def build(ctx: WardrobeContext) -> WardrobePart:
    return WardrobePart("phone", ready=NOT_BUILT)


__all__ = ["build"]
