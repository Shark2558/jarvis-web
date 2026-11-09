# src/jarvis/vitals/brief.py
"""The brief's "Vitals" section (R4) and the board said in one breath (R5.1): amber/red items
(JARVIS's own keys and connections included), then this month's AI spend against the limit, in
rupees. Fixed words, no model call, never part of the AI-summary input. An empty list means
"no section": nothing readable, or the board can't be opened (never an exception in the brief)."""

from __future__ import annotations

from jarvis.logging import get_logger
from jarvis.vitals.models import Board
from jarvis.vitals.service import VitalsService

log = get_logger(__name__)

MAX_LINES = 5
SECTION_TITLE = "Vitals"
SPOKEN_MAX = 700  # about 45 seconds of speech; the panel shows everything


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


def spoken_summary(board: Board) -> str:
    """The whole board as one fixed-template paragraph (what `vitals_show` answers as `spoken`,
    and so what No-AI mode reads out): the count needing attention, each one in words ("Act now"
    / "Watch", never colour), how many can't be read, the AI spend, the manual-records note."""
    hot = board.attention()
    parts = [
        f"Vitals: {len(hot)} need{'s' if len(hot) == 1 else ''} attention."
        if hot
        else "Vitals: nothing needs attention."
    ]
    parts += [
        f"{'Act now' if v.status == 'red' else 'Watch'}: {v.provider.label} {v.reason}."
        for v in hot[:MAX_LINES]
    ]
    if len(hot) > MAX_LINES:
        parts.append(f"And {len(hot) - MAX_LINES} more on the Vitals board.")
    unknown = sum(1 for v in board.items if v.status == "unknown")
    if unknown:
        parts.append(f"{unknown} can't be read just now.")
    if board.spend is not None:
        parts.append(f"AI spend: {board.spend.text}.")
    if board.manual_unavailable:
        parts.append(board.manual_note)
    text = " ".join(parts)
    return text if len(text) <= SPOKEN_MAX else text[: SPOKEN_MAX - 1].rsplit(" ", 1)[0] + "…"


__all__ = ["MAX_LINES", "SECTION_TITLE", "SPOKEN_MAX", "spoken_summary", "vitals_lines"]
