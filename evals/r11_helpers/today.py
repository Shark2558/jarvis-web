# evals/r11_helpers/today.py
"""A's part of the R11 eval (plan docs/plans/r11-free-helpers.md "Tests and evals"): bills and the
prepared UPI payment, birthdays, top priority (control: the taint check off, so an e-mailed UPI
ID becomes a payee).

I0 stub: one passing "not built yet" case and no control. A fills this file (and only this one)
and sets BUILT = True; its control must then make this part fail.
"""

from __future__ import annotations

from typing import Any

PART = "today"
BUILT = False


async def cases() -> list[dict[str, Any]]:
    return [{"id": f"{PART}:not_built_yet", "passed": True, "failures": []}]


async def control() -> dict[str, Any]:
    raise NotImplementedError("A builds the today part and its control")
