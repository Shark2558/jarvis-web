# evals/r14/noai.py
"""R14 eval, Part D's suite (`noai`), I0's stub: No-AI pass 2.
Part D replaces it (BUILT = True only when its negative control really fails it)."""

from __future__ import annotations

from typing import Any

PART = "noai"
BUILT = False


async def cases() -> list[dict[str, Any]]:
    return [{"id": f"{PART}:not_built_yet", "passed": True, "failures": []}]


async def control() -> dict[str, Any]:
    return {"name": "none: not built yet", "suite_failed": True, "failed_cases": []}
