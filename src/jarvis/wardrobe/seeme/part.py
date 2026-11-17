# src/jarvis/wardrobe/seeme/part.py
"""R13.1 Part C's one join (docs/plans/r13-1-try-on.md "Part split" C): I0's STUB, "not built
yet". Part C replaces it: `build(ctx) -> WardrobePart("seeme", daily_jobs=(seeme_daily,),
privacy=..., services={"seeme": ...}, ready=...)`. Its Privacy rows (`tryon_photo`,
`tryon_pictures`, `tryon_spend`) ride `privacy`, never `data` (M4); the try-on provider is
`ctx.tryon()` (None while pictures are off or the adapter is not built). Until then the wiring
gives this part `kept.stand_ins("seeme", ...)`."""

from __future__ import annotations

from jarvis.wardrobe.ports import WardrobeContext, WardrobePart


def build(ctx: WardrobeContext) -> WardrobePart:
    del ctx
    return WardrobePart("seeme")


__all__ = ["build"]
