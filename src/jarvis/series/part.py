# src/jarvis/series/part.py
"""R11.1 Part A (Brain and calendar): the part's one join with the app.

No empty answers, calendar batches, the study-plan follow-up and the inbox summary.

I0 stub: nothing is built yet. Part A replaces the body of `build` and adds its modules to
this package; see docs/plans/r11-1-observations.md and
docs/plans/r11-1-integration/BRIEF-COMMON.md.
"""

from __future__ import annotations

from jarvis.fixes.ports import FixContext, FixPart


def build(ctx: FixContext) -> FixPart:
    del ctx
    return FixPart("plan")


__all__ = ["build"]
