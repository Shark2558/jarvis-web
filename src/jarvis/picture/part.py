# src/jarvis/picture/part.py
"""R11.1 Part D (People, pictures and Vitals): the part's one join with the app.

Profile cards, picture research, clearer Vitals rows.

I0 stub: nothing is built yet. Part D replaces the body of `build` and adds its modules to
this package; see docs/plans/r11-1-observations.md and
docs/plans/r11-1-integration/BRIEF-COMMON.md.
"""

from __future__ import annotations

from jarvis.fixes.ports import FixContext, FixPart


def build(ctx: FixContext) -> FixPart:
    del ctx
    return FixPart("look")


__all__ = ["build"]
