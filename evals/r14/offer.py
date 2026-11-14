# evals/r14/offer.py
"""R14 eval, Part C's suite (`offer`), I0's stub: the turn's tools, the window and the ledger.
Part C replaces it (BUILT = True only when its negative control really fails it)."""

from __future__ import annotations

from typing import Any

PART = "offer"
BUILT = False


async def cases() -> list[dict[str, Any]]:
    return [{"id": f"{PART}:not_built_yet", "passed": True, "failures": []}]


async def control() -> dict[str, Any]:
    return {"name": "none: not built yet", "suite_failed": True, "failed_cases": []}
