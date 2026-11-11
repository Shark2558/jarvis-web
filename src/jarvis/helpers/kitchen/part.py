# src/jarvis/helpers/kitchen/part.py
"""R11 Part D's plug-in (docs/plans/r11-free-helpers.md D2): `build(ctx)` returns everything the app
wires for pantry, recipes, nutrition, grocery spend and cooking / washing-up blocks.

I0 stub: an empty part ("not built yet"). Part D replaces the body; the signature, the module path
and the names in `helpers.kinds` (its kinds, jobs, privacy ids, tool families, collections) stay as
they are.
"""

from __future__ import annotations

from jarvis.helpers.ports import HelperContext, HelperPart


def build(ctx: HelperContext) -> HelperPart:
    return HelperPart(name="kitchen")


__all__ = ["build"]
