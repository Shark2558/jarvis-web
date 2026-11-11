# src/jarvis/helpers/house/part.py
"""R11 Part B's plug-in (docs/plans/r11-free-helpers.md D2): `build(ctx)` returns everything the app
wires for the chores rota, home upkeep, weather, disaster alerts and breach notices.

I0 stub: an empty part ("not built yet"). Part B replaces the body; the signature, the module path
and the names in `helpers.kinds` (its kinds, jobs, privacy ids, tool families, collections) stay as
they are.
"""

from __future__ import annotations

from jarvis.helpers.ports import HelperContext, HelperPart


def build(ctx: HelperContext) -> HelperPart:
    return HelperPart(name="house")


__all__ = ["build"]
