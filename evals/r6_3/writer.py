# evals/r6_3/writer.py
"""R6.3 eval, part B's `writer` suite (evals/r6_3/run.py; plan "Tests and evals"). I0's stub:
not built yet. B replaces this file: its cases (each the eval case of a named test), its
negative controls (each must turn its case red), then `BUILT = True`.
"""

from __future__ import annotations

from typing import Any

PART = "writer"
BUILT = False


async def cases() -> list[dict[str, Any]]:
    return [{"id": f"{PART}:not_built_yet", "passed": True, "failures": []}]


async def control() -> dict[str, Any]:
    return {"name": "not built yet", "suite_failed": False, "failed_cases": []}
