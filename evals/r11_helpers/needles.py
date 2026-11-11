# evals/r11_helpers/needles.py
"""I1's part of the R11 eval (plan docs/plans/r11-free-helpers.md "Tests and evals"):
`r11_needles`: after a day of every part on fakes, no planted needle (a card number, a birth
year, an e-mailed UPI ID, a CAP instruction, a pantry note, a water count) in any document, log,
audit detail, Activity row, alert or brief text (control: masking off).

I0 stub: one passing "not built yet" case and no control. I1 fills this file (and only this one)
and sets BUILT = True; its control must then make this part fail.
"""

from __future__ import annotations

from typing import Any

PART = "needles"
BUILT = False


async def cases() -> list[dict[str, Any]]:
    return [{"id": f"{PART}:not_built_yet", "passed": True, "failures": []}]


async def control() -> dict[str, Any]:
    raise NotImplementedError("I1 builds the needles part and its control")
