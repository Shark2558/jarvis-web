# evals/r11_helpers/kitchen.py
"""D's part of the R11 eval (plan docs/plans/r11-free-helpers.md "Tests and evals"): recipes with
the code diet check and No-AI, nutrition, receipts, calendar blocks (control: the diet check
off).

I0 stub: one passing "not built yet" case and no control. D fills this file (and only this one)
and sets BUILT = True; its control must then make this part fail.
"""

from __future__ import annotations

from typing import Any

PART = "kitchen"
BUILT = False


async def cases() -> list[dict[str, Any]]:
    return [{"id": f"{PART}:not_built_yet", "passed": True, "failures": []}]


async def control() -> dict[str, Any]:
    raise NotImplementedError("D builds the kitchen part and its control")
