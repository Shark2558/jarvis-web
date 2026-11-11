# evals/r11_helpers/house.py
"""B's part of the R11 eval (plan docs/plans/r11-free-helpers.md "Tests and evals"): chores,
upkeep, Open-Meteo thresholds, SACHET CAP alerts, breach notices (control: the district filter
off).

I0 stub: one passing "not built yet" case and no control. B fills this file (and only this one)
and sets BUILT = True; its control must then make this part fail.
"""

from __future__ import annotations

from typing import Any

PART = "house"
BUILT = False


async def cases() -> list[dict[str, Any]]:
    return [{"id": f"{PART}:not_built_yet", "passed": True, "failures": []}]


async def control() -> dict[str, Any]:
    raise NotImplementedError("B builds the house part and its control")
