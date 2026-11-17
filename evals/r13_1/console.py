# evals/r13_1/console.py
"""R13.1 eval, Part D (console and phone):
I0's STUB (docs/plans/r13-1-try-on.md "Tests and evals").
D replaces it: BUILT = True only once its control really fails the part (`control()` re-runs
its cases with the control applied). Until I1, a stub passes as "console:not_built_yet"
(`run.STUBS_PASS`)."""

from __future__ import annotations

from typing import Any

PART = "console"
BUILT = False


async def cases() -> list[dict[str, Any]]:
    return [{"id": f"{PART}:not_built_yet", "passed": True, "failures": []}]


async def control() -> dict[str, Any]:
    return {"name": "none: not built yet", "suite_failed": False, "failed_cases": []}
