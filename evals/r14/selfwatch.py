# evals/r14/selfwatch.py
"""R14 eval, Part B's suite (`selfwatch`), I0's stub: self-health.
Part B replaces it (BUILT = True only when its negative control really fails it)."""

from __future__ import annotations

from typing import Any

PART = "selfwatch"
BUILT = False


async def cases() -> list[dict[str, Any]]:
    return [{"id": f"{PART}:not_built_yet", "passed": True, "failures": []}]


async def control() -> dict[str, Any]:
    return {"name": "none: not built yet", "suite_failed": True, "failed_cases": []}
