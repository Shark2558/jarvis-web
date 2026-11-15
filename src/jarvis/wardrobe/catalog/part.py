# src/jarvis/wardrobe/catalog/part.py
"""R13 Part A's one join (docs/plans/r13-wardrobe.md "Part split"): catalog.

Catalog and the ledger (INV-01-17, OPS-03, OPS-06).

I0 stub: `build` answers "not built yet". Part A fills it: `build(ctx: WardrobeContext) ->
WardrobePart("catalog", ...)` with only its own tools, jobs, services and data
(`jarvis.wardrobe.ports`); `api/r13_wiring.py` leaves out a part that breaks the contract.
"""

from __future__ import annotations

from jarvis.wardrobe.ports import NOT_BUILT, WardrobeContext, WardrobePart


def build(ctx: WardrobeContext) -> WardrobePart:
    return WardrobePart("catalog", ready=NOT_BUILT)


__all__ = ["build"]
