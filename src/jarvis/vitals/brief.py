# src/jarvis/vitals/brief.py
"""The brief's "Vitals" section (R4): amber/red items, then this month's AI spend against the limit,
in rupees. Fixed words, no model call, never part of the AI-summary input. An empty list means
"no section": nothing readable, or the board can't be opened (never an exception in the brief)."""

from __future__ import annotations

from jarvis.logging import get_logger
from jarvis.vitals.service import VitalsService

log = get_logger(__name__)

MAX_LINES = 5
SECTION_TITLE = "Vitals"


async def vitals_lines(service: VitalsService, uid: str) -> list[str]:
    try:
        board = await service.board(uid)
    except Exception as exc:  # noqa: BLE001 - the brief never fails because of Vitals
        log.warning("brief: vitals unavailable", extra={"error": type(exc).__name__})
        return []
    hot = board.attention()
    lines = [
        f"{'Red' if v.status == 'red' else 'Amber'}: {v.provider.label} {v.reason}"
        for v in hot[:MAX_LINES]
    ]
    if len(hot) > MAX_LINES:
        lines.append(f"and {len(hot) - MAX_LINES} more in Vitals")
    if board.spend is not None:
        lines.append(f"AI spend: {board.spend.text}")
    return lines


__all__ = ["MAX_LINES", "SECTION_TITLE", "vitals_lines"]
