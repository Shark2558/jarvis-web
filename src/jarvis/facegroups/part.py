# src/jarvis/facegroups/part.py
"""R11.1 Part C (Photos, faces and the home kit): the part's one join with the app.

Google Photos picks, the laptop's photo folder, face groups.

I0 stub: nothing is built yet. Part C replaces the body of `build` and adds its modules to
this package; see docs/plans/r11-1-observations.md and
docs/plans/r11-1-integration/BRIEF-COMMON.md.
"""

from __future__ import annotations

from jarvis.fixes.ports import FixContext, FixPart


def build(ctx: FixContext) -> FixPart:
    del ctx
    return FixPart("photos")


__all__ = ["build"]
