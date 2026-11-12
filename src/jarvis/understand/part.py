# src/jarvis/understand/part.py
"""R11.1 Part B (Voice and files): the part's one join with the app.

Spoken words understood, and more kinds of files.

I0 stub: nothing is built yet. Part B replaces the body of `build` and adds its modules to
this package; see docs/plans/r11-1-observations.md and
docs/plans/r11-1-integration/BRIEF-COMMON.md.
"""

from __future__ import annotations

from jarvis.fixes.ports import FixContext, FixPart


def build(ctx: FixContext) -> FixPart:
    del ctx
    return FixPart("files")


__all__ = ["build"]
