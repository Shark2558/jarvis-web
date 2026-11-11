# src/jarvis/helpers/nudges/part.py
"""R11 Part C's plug-in (docs/plans/r11-free-helpers.md D2): `build(ctx)` returns everything the app
wires for stand-up, water, a planned activity that didn't happen, free-time ideas and the focus
nudge.

I0 stub: an empty part ("not built yet"). Part C replaces the body; the signature, the module path
and the names in `helpers.kinds` (its kinds, jobs, privacy ids, tool families, collections) stay as
they are.
"""

from __future__ import annotations

from jarvis.helpers.ports import HelperContext, HelperPart


def build(ctx: HelperContext) -> HelperPart:
    return HelperPart(name="nudges")


__all__ = ["build"]
