# evals/r7/shell.py
"""R7 eval, Part A (`shell`): see evals/r7/run.py for the cases this file must hold.
I0 stub: Part A writes the cases and the negative control, then sets BUILT = True (only
when the control really makes the cases fail)."""

from __future__ import annotations

from typing import Any

PART = "shell"
BUILT = False


async def cases() -> list[dict[str, Any]]:
    print(f"{PART}: not built yet")
    return [{"id": f"{PART}:not_built_yet", "passed": True, "failures": []}]


async def control() -> dict[str, Any]:
    return {"name": f"{PART}: no control yet", "suite_failed": False, "failed_cases": []}
