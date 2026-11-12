# src/jarvis/core/finish.py
"""Finishing a reply (R11.1 I0; docs/plans/r11-1-observations.md D1-D3; Layer 4).

What the Brain does with a model's answer once the tool loop has ended lives here, outside
`brain.py` (which is near its size guard): the words of the reply, whether the answer was cut
short, how many output tokens a turn may use, and the turn's log line.

I0 moved the code as it was: an answer with no words still becomes `FILLER`. Part A replaces that
(D2): check `cut_short`, retry once without tools' leftovers, then say plainly what went wrong and
what to do; a filler is never stored as an assistant turn (D3).
"""

from __future__ import annotations

from jarvis.config import Settings
from jarvis.core.models import Session
from jarvis.llm.base import Completion
from jarvis.llm.brains import BrainSpec
from jarvis.logging import get_logger

log = get_logger("jarvis.core.brain")  # the Brain's own log name: dashboards filter on it

FILLER = "I have nothing to add, Sir."
CUT_REASONS = frozenset({"max_tokens", "length"})


def reply_text(completion: Completion) -> str:
    """The reply's words. I0: unchanged behaviour (Part A, D2: no filler)."""
    return completion.text.strip() or FILLER


def cut_short(completion: Completion) -> bool:
    """The vendor stopped because the output cap was reached, not because it had finished."""
    return completion.stop_reason in CUT_REASONS


def output_cap(s: Settings, *, working: bool) -> int:
    """Output tokens one model call may use: a turn that works with tools or attached files gets
    `work_output_tokens`, a plain chat reply `max_output_tokens` (D1). Never below the plain cap."""
    return max(s.max_output_tokens, s.work_output_tokens) if working else s.max_output_tokens


def log_turn(
    session: Session, window: int, spec: BrainSpec, completion: Completion, total_ms: int
) -> None:
    log.info(
        "brain: turn complete",
        extra={
            "session_id": session.id,
            "turns": len(session.turns),
            "window": window,
            "brain": spec.id,
            "model": completion.model,
            "cost_usd": completion.cost_usd,
            "llm_ms": completion.latency_ms,
            "total_ms": total_ms,
        },
    )


__all__ = ["CUT_REASONS", "FILLER", "cut_short", "log_turn", "output_cap", "reply_text"]
