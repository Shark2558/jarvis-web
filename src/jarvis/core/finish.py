# src/jarvis/core/finish.py
"""Finishing a reply (R11.1; docs/plans/r11-1-observations.md D1-D3; Layer 4).

What the Brain does with a model's answer lives here, outside `brain.py` (near its size guard):

- `output_cap`, `working_turn` (D1): a turn that works with tools or attached files may write
  `work_output_tokens`; a plain chat reply, an approval's narration and a training brain keep
  `max_output_tokens`. A cap is a ceiling, not a spend.
- `asked`, `retried` (D2.2): an answer the cap cut off before it said anything usable (no words,
  or tool calls that may be half-written) is asked for ONCE more per owner message: the same
  call with the working cap and one fixed instruction (`RETRY`), admitted and metered like any
  call. A cut-off answer's tool calls never run and it is never stored. Still unfinished, or the
  retry could not be made: an answer with no words and no calls.
- `reply_text` (D2.1, D2.3): the reply's words, or one fixed, honest line chosen by CODE from what
  happened (approvals waiting, steps that ran, cut off, simply empty). Never the old filler.
- `is_fixed` (D3): those lines, and the filler R11 and earlier stored (`OLD_FILLER`), are known
  by their words. `reply_turn` stores one marked tool-derived (never to a training brain) and
  `core.window` leaves it out of every model's window, so no later turn can imitate it; stored
  conversations recover without a migration.
- `said_by_code` (D5): what an approved card did, in the tool's own fixed sentence, for when no
  model may report it (No-AI mode, the monthly limit, an outage, a brain that may train): a
  batch that added 58 of 60 is never reported as "Done, Sir: Add 60 events".
- `chat_response`, `log_turn`: the response and the turn's log line.

`FILLER` is I0's name for "what an answer with no words becomes": it is now `EMPTY`.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from jarvis.billing import BudgetError
from jarvis.config import Settings
from jarvis.core.brain_types import _ReplyMeta
from jarvis.core.channel import answered_offline
from jarvis.core.models import ChatResponse, Session, Turn
from jarvis.llm.base import ChatMessage, Completion, LLMError, Role, StreamUsage, Usage
from jarvis.llm.brains import BrainSpec
from jarvis.logging import get_logger
from jarvis.tools.gateway import GatewayOutcome, GatewayResult
from jarvis.web.ledger import cited_sources

log = get_logger("jarvis.core.brain")  # the Brain's own log name: dashboards filter on it

# What R11 and earlier said (and stored) for an answer with no words. Only ever matched now.
OLD_FILLER = "I have nothing to add, Sir."
CUT_TAIL = "Ask me for a smaller piece, or raise the answer length in Settings."
CUT_OFF = f"My answer was cut off before I could finish, Sir. {CUT_TAIL}"
CUT_ALSO = "My answer was cut off before I could finish."  # after another sentence's "Sir"
EMPTY = (
    "The AI returned an empty answer, Sir. Please ask again; if it repeats, switch brain in the "
    "top bar."
)
FILLER = EMPTY
RETRY = (
    "Answer in words now. If the work needs many tool calls, use the batch tool or say what "
    "remains."
)
CUT_REASONS = frozenset({"max_tokens", "length"})
# Tools whose result's `message` is ONE sentence written by code alone: counts and JARVIS's own
# words, never a title or anything a file or a mail said (`series.batch_result`, `series.cards`).
SAID_BY_CODE = frozenset(
    {"calendar_create_events", "calendar_undo_events", "series_checkin", "series_reschedule"}
)
SAID_MAX = 400
_CARDS = r"I've prepared \d+ approvals? for you, Sir\."
_STEPS = (
    r"I did \d+ steps? but the AI gave me no words to report (?:it|them)\. "
    r"Activity shows what ran\."
)
_CUT = rf"My answer was cut off before I could finish(?:, Sir)?\. {re.escape(CUT_TAIL)}"
_FIXED = re.compile(rf"(?:{_CARDS})?(?: ?{_STEPS})?(?: ?{_CUT})?")

# One model call of a turn: (the messages, whether it gets the working cap) -> its answer.
ModelCall = Callable[[list[ChatMessage], bool], Awaitable[Completion]]


@dataclass
class Tries:
    """Retries one owner message may still spend (`empty_reply_retries`). Mutable on purpose:
    every model call of the message shares it."""

    left: int


# ---- the output cap (D1) ------------------------------------------------------------------------


def output_cap(s: Settings, *, working: bool) -> int:
    """Output tokens one model call may use: a turn that works with tools or attached files gets
    `work_output_tokens`, a plain chat reply `max_output_tokens` (D1). Never below the plain cap."""
    return max(s.max_output_tokens, s.work_output_tokens) if working else s.max_output_tokens


def working_turn(spec: BrainSpec, *, tools: bool, attachments: bool) -> bool:
    """A turn that has tools on or carries attached files; never a training brain's (D1)."""
    return spec.tools_allowed and (tools or attachments)


# ---- cut off: one retry (D2.2) ------------------------------------------------------------------


def cut_short(completion: Completion) -> bool:
    """The vendor stopped because the output cap was reached, not because it had finished."""
    return completion.stop_reason in CUT_REASONS


def unfinished(completion: Completion) -> bool:
    """Cut off with nothing usable: no words, or tool calls (the last may be half-written, and a
    batch acted on in part is worse than none). Cut-off WORDS are still the reply."""
    return cut_short(completion) and (bool(completion.tool_calls) or not completion.text.strip())


def _nothing(completion: Completion) -> Completion:
    """`completion`'s cost and counts, with no words and no calls: `reply_text` says "cut off"."""
    return completion.model_copy(update={"text": "", "tool_calls": [], "stop_reason": "max_tokens"})


def plus(a: Usage | None, b: Usage | None) -> Usage:
    """Two calls' token counts as one (the conversation's totals come from stored turns)."""
    a, b = a or Usage(), b or Usage()
    return Usage(
        input_tokens=a.input_tokens + b.input_tokens,
        output_tokens=a.output_tokens + b.output_tokens,
        cache_read_tokens=a.cache_read_tokens + b.cache_read_tokens,
        cache_write_tokens=a.cache_write_tokens + b.cache_write_tokens,
        estimated=a.estimated or b.estimated,
    )


async def retried(
    first: Completion, call: ModelCall, msgs: list[ChatMessage], tries: Tries
) -> Completion:
    """`first` when it is usable. Cut off with nothing usable: the call once more (if this owner
    message still has a retry), with `RETRY` after `msgs` and the working cap. The answer that
    comes back carries both calls' cost; when it is unfinished too, or the retry could not be
    made (the monthly limit, the provider), it has no words and no calls."""
    if not unfinished(first):
        return first
    if tries.left <= 0:
        return _nothing(first)
    tries.left -= 1
    log.warning(
        "brain: answer cut off by the output cap; asking once more",
        extra={"had_calls": len(first.tool_calls), "out_tok": first.usage.output_tokens},
    )
    try:
        again = await call([*msgs, ChatMessage(role=Role.USER, content=RETRY)], True)
    except (LLMError, BudgetError) as exc:  # the first call stands: say "cut off", never fail
        log.warning("brain: the retry could not be made", extra={"error": type(exc).__name__})
        return _nothing(first)
    both = again.model_copy(
        update={
            "usage": plus(first.usage, again.usage),
            "cost_usd": first.cost_usd + again.cost_usd,
            "latency_ms": first.latency_ms + again.latency_ms,
        }
    )
    if unfinished(both):
        log.warning("brain: still cut off after the retry", extra={"model": both.model})
        return _nothing(both)
    return both


async def asked(
    call: ModelCall, msgs: list[ChatMessage], tries: Tries, *, working: bool
) -> Completion:
    """One model call of an owner message, retried once when its answer was cut off (D2.2)."""
    return await retried(await call(msgs, working), call, msgs, tries)


def silent(model: str, reported: StreamUsage, cap: int) -> Completion:
    """A stream that ended with no words, as an answer `retried` and `reply_text` can judge: cut
    off when the vendor's closing count says the whole cap was written (a stream carries no stop
    reason). Its cost is already metered by the stream."""
    cut = reported.final and (reported.output_tokens or 0) >= cap
    return Completion(
        text="",
        model=model,
        provider="",
        usage=Usage(),
        stop_reason="max_tokens" if cut else "end_turn",
        latency_ms=0,
    )


# ---- the reply's words (D2.1, D2.3) and their marking (D3) ---------------------------------------


def _count(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def reply_text(completion: Completion, *, cards: int = 0, steps: int = 0) -> str:
    """The reply's words. With none: one fixed line chosen from what happened, never from the
    model: the approvals now waiting (`cards`), the tool calls that ran (`steps`), a cut-off
    answer; an answer that is simply empty says so and what to do."""
    words = completion.text.strip()
    if words:
        return words
    parts: list[str] = []
    if cards > 0:
        parts.append(f"I've prepared {_count(cards, 'approval')} for you, Sir.")
    if steps > 0:
        them = "it" if steps == 1 else "them"
        parts.append(
            f"I did {_count(steps, 'step')} but the AI gave me no words to report {them}. "
            "Activity shows what ran."
        )
    if cut_short(completion):
        parts.append(f"{CUT_ALSO} {CUT_TAIL}" if parts else CUT_OFF)
    return " ".join(parts) or EMPTY


def is_fixed(text: str) -> bool:
    """`text` is one of JARVIS's own fixed lines for an answer with no words (or the old filler):
    never history for a model (`core.window`), stored marked tool-derived (`reply_turn`)."""
    t = text.strip()
    return bool(t) and (t in (EMPTY, OLD_FILLER) or _FIXED.fullmatch(t) is not None)


def reply_turn(
    session: Session,
    spec: BrainSpec,
    reply: str,
    completion: Completion,
    trace_id: str | None,
    *,
    after_tools: bool,
) -> Turn:
    """The stored reply. Written from tool results, or one of our own fixed lines: tool-derived,
    so it never reaches a brain that may train on content."""
    return Turn(
        role=Role.ASSISTANT,
        content=reply,
        trace_id=trace_id,
        model=completion.model,
        usage=completion.usage,
        cost_usd=completion.cost_usd,
        latency_ms=completion.latency_ms,
        tool_derived=after_tools or is_fixed(reply),
        offline=completion.offline or answered_offline(),
        sources=cited_sources(reply, session, enabled=spec.tools_allowed),
    )


def chat_response(
    session: Session,
    brain_id: str,
    reply: str,
    completion: Completion,
    meta: _ReplyMeta,
    inr: tuple[float, ...],
) -> ChatResponse:
    """One turn's ChatResponse; `inr` = (this reply, the whole conversation) in rupees."""
    cost_inr, total_inr = inr
    return ChatResponse(
        session_id=session.id,
        reply=reply,
        trace_id=meta.trace_id,
        model=completion.model,
        brain=brain_id,
        usage=completion.usage,
        cost_usd=completion.cost_usd,
        cost_inr=cost_inr,
        total_cost_usd=session.total_cost_usd,
        total_cost_inr=total_inr,
        latency_ms=meta.total_ms,
        turn_count=len(session.turns),
        tool_calls=meta.rounds,
        pending_approvals=meta.pending,
        memory_used=meta.memory_used,
        offline=session.turns[-1].offline,
        sources=session.turns[-1].sources,  # the reply just stored: what it cited
        undo=meta.undo,
        cards=meta.cards,
    )


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


def said_by_code(tool: str, result: GatewayResult) -> str | None:
    """The tool's own fixed sentence for a call that ran, or None (any other tool, a call that
    did not run, or no such sentence)."""
    if tool not in SAID_BY_CODE or result.outcome is not GatewayOutcome.EXECUTED:
        return None
    said = result.result.get("message") if isinstance(result.result, dict) else None
    return said if isinstance(said, str) and 0 < len(said) <= SAID_MAX else None


__all__ = [
    "CUT_OFF",
    "CUT_REASONS",
    "EMPTY",
    "FILLER",
    "OLD_FILLER",
    "RETRY",
    "ModelCall",
    "Tries",
    "asked",
    "chat_response",
    "cut_short",
    "is_fixed",
    "log_turn",
    "output_cap",
    "plus",
    "reply_text",
    "reply_turn",
    "retried",
    "said_by_code",
    "silent",
    "unfinished",
    "working_turn",
]
