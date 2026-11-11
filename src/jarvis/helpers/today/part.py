# src/jarvis/helpers/today/part.py
"""R11 Part A's plug-in (docs/plans/r11-free-helpers.md D2): `build(ctx)` returns everything the app
wires for bills and the prepared UPI payment, birthdays, top priority and what is pending.

I0 stub: an empty part ("not built yet"). Part A replaces the body; the signature, the module path
and the names in `helpers.kinds` (its kinds, jobs, privacy ids, tool families, collections) stay as
they are.
"""

from __future__ import annotations

from jarvis.helpers.ports import HelperContext, HelperPart


def build(ctx: HelperContext) -> HelperPart:
    return HelperPart(name="today")


__all__ = ["build"]
