# evals/r14/needles.py
"""R14 eval, I1's suite (`needles`), I0's stub: nothing private written down where it must not be.
I1 replaces it (BUILT = True only when its negative control really fails it)."""

from __future__ import annotations

from typing import Any

PART = "needles"
BUILT = False


async def cases() -> list[dict[str, Any]]:
    return [{"id": f"{PART}:not_built_yet", "passed": True, "failures": []}]


async def control() -> dict[str, Any]:
    return {"name": "none: not built yet", "suite_failed": True, "failed_cases": []}
