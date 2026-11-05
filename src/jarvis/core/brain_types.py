# src/jarvis/core/brain_types.py
"""Small value types `core.brain` passes between its steps (split out to keep `brain.py` short)."""

from __future__ import annotations

from dataclasses import dataclass, field

from jarvis.core.models import ChatRequest, PendingApproval, Turn, UndoRef
from jarvis.llm.base import Role
from jarvis.recall.models import MemoryRef
from jarvis.tools.reply_cards import AnyCard


def _owner_turn(text: str, req: ChatRequest, trace_id: str | None) -> Turn:
    """The owner's message, marked with how it arrived (a spoken one is never learned from)."""
    return Turn(role=Role.USER, content=text, trace_id=trace_id, channel=req.channel)


@dataclass(frozen=True)
class _Prompt:
    """One turn's prompt: the persona (read once per turn) and the per-request trailer."""

    system: str
    trailer: str


@dataclass(frozen=True)
class _ReplyMeta:
    trace_id: str
    total_ms: int
    rounds: int
    pending: list[PendingApproval]
    memory_used: list[MemoryRef]
    undo: list[UndoRef] = field(default_factory=list)  # slice 11: the reply's Undo chips
    cards: list[AnyCard] = field(default_factory=list)  # slice 12: Maps / YouTube / drafts
