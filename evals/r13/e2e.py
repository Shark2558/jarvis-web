# evals/r13/e2e.py
"""R13 eval, I1's suite (`e2e`), I0's stub: the workbook's end-to-end tests 1-5, 7 and 8.
I1 replaces it (BUILT = True only when its negative control really fails it)."""

from __future__ import annotations

from typing import Any

PART = "e2e"
BUILT = False


async def cases() -> list[dict[str, Any]]:
    return [{"id": f"{PART}:not_built_yet", "passed": True, "failures": []}]


async def control() -> dict[str, Any]:
    return {"name": "none: not built yet", "suite_failed": True, "failed_cases": []}
