# src/jarvis/wardrobe/tryon/part.py
"""R13.1 Part A's one join (docs/plans/r13-1-try-on.md "Part split" A): I0's STUB, "not built
yet". Part A replaces it: `build(ctx) -> WardrobePart("tryon", privacy=..., services=
{"tryon_looks": ...}, ready=...)`. Its Privacy rows (`tryon_figure`, `tryon_all`, `tryon_device`)
ride `privacy`, never `data` (the wiring refuses a `tryon` part with data, M4). Until then the
wiring gives this part `kept.stand_ins("tryon", ...)`."""

from __future__ import annotations

from jarvis.wardrobe.ports import WardrobeContext, WardrobePart


def build(ctx: WardrobeContext) -> WardrobePart:
    del ctx
    return WardrobePart("tryon")


__all__ = ["build"]
