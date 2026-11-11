# evals/r11_helpers/nudges.py
"""C's part of the R11 eval (plan docs/plans/r11-free-helpers.md "Tests and evals"): stand-up,
water, a missed activity, free time, snooze / stop by phrase, 14 days on time (control: claims
off, so a restart sends twice).

I0 stub: one passing "not built yet" case and no control. C fills this file (and only this one)
and sets BUILT = True; its control must then make this part fail.
"""

from __future__ import annotations

from typing import Any

PART = "nudges"
BUILT = False


async def cases() -> list[dict[str, Any]]:
    return [{"id": f"{PART}:not_built_yet", "passed": True, "failures": []}]


async def control() -> dict[str, Any]:
    raise NotImplementedError("C builds the nudges part and its control")
