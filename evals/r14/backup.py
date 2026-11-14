# evals/r14/backup.py
"""R14 eval, Part A's suite (`backup`), I0's stub: backups and the restore drill.
Part A replaces it (BUILT = True only when its negative control really fails it)."""

from __future__ import annotations

from typing import Any

PART = "backup"
BUILT = False


async def cases() -> list[dict[str, Any]]:
    return [{"id": f"{PART}:not_built_yet", "passed": True, "failures": []}]


async def control() -> dict[str, Any]:
    return {"name": "none: not built yet", "suite_failed": True, "failed_cases": []}
