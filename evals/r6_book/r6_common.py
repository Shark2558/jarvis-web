# evals/r6_book/r6_common.py
"""Shared by the R6 build-book eval parts (evals/r6_book/*.py): the part interface and the I0
stub answer. See run.py for the interface every part file exposes."""

from __future__ import annotations

from typing import Any

Case = dict[str, Any]


def not_built(part: str, planned: tuple[str, ...]) -> list[Case]:
    """An I0 stub's one case: it passes, says the part isn't built yet and lists its plan."""
    return [
        {
            "id": f"{part}:not_built_yet",
            "passed": True,
            "failures": [],
            "note": "not built yet",
            "planned": list(planned),
        }
    ]


def no_control(part: str) -> dict[str, Any]:
    """A stub has no negative control yet (run.py only asks a BUILT part for one)."""
    return {"name": f"{part}: none (not built yet)", "suite_failed": False, "failed_cases": []}


__all__ = ["Case", "no_control", "not_built"]
