# src/jarvis/whatsapp/cards.py
"""The draft cards a reply carries (slice 12 D6; Layer 3 → 8): read from the calls that ran.

Like the Undo chips (`core.rounds.undo_refs`): only from the registered whatsapp_draft tool, only
for a call that EXECUTED, and only from a result that is a real draft (`draft.card_from_result`
re-checks it and rebuilds the link). At most `MAX_CARDS` per reply. Never raises: the call
already ran, and bookkeeping after it must never turn it into an error.
"""

from __future__ import annotations

from collections.abc import Sequence

from jarvis.llm.base import ToolCall
from jarvis.logging import get_logger
from jarvis.tools.gateway import GatewayOutcome, GatewayResult
from jarvis.tools.registry import ToolRegistry
from jarvis.whatsapp.draft import DraftCard, card_from_result
from jarvis.whatsapp.tools import TOOL

log = get_logger(__name__)
MAX_CARDS = 5


def capped(have: Sequence[DraftCard], new: Sequence[DraftCard]) -> list[DraftCard]:
    """A reply's draft cards after more arrive: the first MAX_CARDS, in order (review C9)."""
    return [*have, *new][:MAX_CARDS]


def draft_cards(
    registry: ToolRegistry, calls: Sequence[ToolCall], results: Sequence[GatewayResult]
) -> list[DraftCard]:
    out: list[DraftCard] = []
    try:
        for call, gr in zip(calls, results, strict=True):
            if call.name != TOOL or registry.get(TOOL) is None:
                continue
            if gr.outcome is not GatewayOutcome.EXECUTED:
                continue
            card = card_from_result(gr.result)
            if card is not None and len(out) < MAX_CARDS:
                out.append(card)
    except Exception as exc:  # noqa: BLE001 — a lost card: the owner can ask again
        log.warning("whatsapp draft card not made", extra={"error": type(exc).__name__})
    return out


__all__ = ["MAX_CARDS", "capped", "draft_cards"]
