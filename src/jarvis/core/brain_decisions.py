# src/jarvis/core/brain_decisions.py
"""The owner's approve / decline of a waiting action, before it is narrated (Layer 4).

Split out of `jarvis.core.brain` (slice 10 integration) so the core loop stays small; the Brain
still owns the order of events (`Brain._decide_locked`): run or cancel the action here, store
its tool exchange BEFORE any model call (`record_exchange` + `jarvis.core.saving`), then narrate.

- `approved`: runs the call through the gateway with the approval token. A lost race (the token
  is spent or expired) raises LookupError and touches nothing; a card that changed since the
  owner saw it (slice 10 D) is withdrawn and proposed again — nothing ran. An approved
  undo-able delete carries its Undo chip (`Decision.undo`, slice 11), worked out so that it can
  never raise after the call ran (a lost chip leaves the copy in Recently deleted).
- `declined`: cancels the card (a concurrent decision raises LookupError, so a decline that did
  not happen is never recorded) and audits it.
- `Outcome`: what a decision — one card, or Approve all (`jarvis.core.approve_all`) — did, ready
  for its one reply (`Brain._narrated`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from jarvis.core.channel import answered_offline
from jarvis.core.guardrails import PendingAction
from jarvis.core.models import ChatResponse, PendingApproval, Session, Turn, UndoRef
from jarvis.core.rounds import undo_refs
from jarvis.llm.base import Completion, Role, TextBlock, ToolCall, Usage
from jarvis.logging import get_logger
from jarvis.tools.gateway import Gateway, GatewayOutcome, GatewayResult
from jarvis.tools.reply_cards import AnyCard, collecting_cards

log = get_logger(__name__)


@dataclass(frozen=True)
class Decision:
    """What an owner's approve / decline produced, before it is narrated."""

    call: ToolCall
    result: GatewayResult
    fallback: str
    instruction: str
    undo: tuple[UndoRef, ...] = ()  # slice 11: an approved undo-able delete's Undo chip
    cards: tuple[AnyCard, ...] = ()  # slice 12: an approved call's reply cards


@dataclass(frozen=True)
class Outcome:
    """What an owner decision did, ready for its one reply."""

    fallback: str  # the plain reply when the model can't (or mustn't) narrate
    unrecorded: list[Turn]  # its exchange turns not stored yet: retried with the narration
    did: bool  # something ran (the "not recorded" note says "It was done")
    tool_calls: int = 0
    again: list[PendingAction] = field(default_factory=list)  # cards proposed again
    note: str = ""  # added to the reply as written (Approve all: the cards left waiting)
    narrate: bool = True  # False: nothing ran or was recorded — no model call, nothing stored
    undo: list[UndoRef] = field(default_factory=list)  # undo-able deletes that ran: Undo chips
    cards: list[AnyCard] = field(default_factory=list)  # slice 12: Maps / YouTube / drafts


def single(d: Decision, *, approved: bool, unrecorded: list[Turn]) -> Outcome:
    """The outcome of one approve / decline. Done only when the call reached its tool (it
    returned, or raised while running): a refusal at approval time, a re-proposed card or an
    unwritable audit is nothing done (as Approve all counts it, C review LOW-3)."""
    did = approved and d.result.ran
    again = [d.result.pending] if d.result.pending is not None else []
    undo, cards = list(d.undo), list(d.cards)
    return Outcome(
        d.fallback, unrecorded, did, tool_calls=int(did), again=again, undo=undo, cards=cards
    )


def narration(reply: str, completion: Completion | None, trace_id: str) -> Turn:
    """The reply to a decision: tool-derived, so never sent to a brain that may train on it."""
    return Turn(
        role=Role.ASSISTANT,
        content=reply,
        trace_id=trace_id,
        model=completion.model if completion else "none",
        usage=completion.usage if completion else None,
        cost_usd=completion.cost_usd if completion else 0.0,
        tool_derived=True,
    )


def response(
    session: Session,
    brain_id: str,
    reply: str,
    completion: Completion | None,
    trace_id: str,
    out: Outcome,
    inr: tuple[float, ...],
) -> ChatResponse:
    """The decision's ChatResponse; `inr` = (this reply, the whole conversation) in rupees."""
    cost_inr, total_inr = inr
    return ChatResponse(
        session_id=session.id,
        reply=reply,
        trace_id=trace_id,
        model=completion.model if completion else "none",
        brain=brain_id,
        usage=completion.usage if completion else Usage(),
        cost_usd=completion.cost_usd if completion else 0.0,
        offline=bool(completion and completion.offline) or answered_offline(),
        cost_inr=cost_inr,
        total_cost_usd=session.total_cost_usd,
        total_cost_inr=total_inr,
        latency_ms=0,
        turn_count=len(session.turns),
        tool_calls=out.tool_calls,
        pending_approvals=[PendingApproval.from_action(a) for a in out.again],
        undo=list(out.undo),
        cards=list(out.cards),
    )


def record_exchange(session: Session, d: Decision, trace_id: str | None) -> list[Turn]:
    """The decided action as a tool exchange (tool_use → tool_result + instruction). The result
    is trusted only when it ran and the gateway found it the owner's own (slice 11 D8)."""
    result = d.result.block(d.call.id, is_error=d.result.outcome is not GatewayOutcome.EXECUTED)
    turns = [
        Turn(role=Role.ASSISTANT, content="", blocks=[d.call], trace_id=trace_id),
        Turn(
            role=Role.USER, content="", blocks=[result, TextBlock(text=d.instruction)],
            trace_id=trace_id,
        ),
    ]  # fmt: skip
    for t in turns:
        session.append(t)
    return turns


async def approved(
    gateway: Gateway,
    call: ToolCall,
    action: PendingAction,
    approval_id: str,
    scope: str,
    shown: Sequence[AnyCard] = (),
) -> Decision:
    """Run the approved call. `shown`: the cards its reply already carries (Approve all), so the
    reply's caps hold and a tool told the reply is full says so instead of dropping its card."""
    cards: list[AnyCard] = list(shown)
    with collecting_cards(cards):  # slice 12: an approved call shows its card (Maps, a draft)
        gr = await gateway.execute(call, confirmation_id=approval_id, scope=scope)
    made = tuple(cards[len(shown) :])
    if gr.outcome is GatewayOutcome.CONFIRMATION_INVALID:
        # lost a race with another approve/decline: nothing ran, touch nothing
        raise LookupError(f"no pending approval {approval_id} in this session")
    if (changed := gr.changed_card()) is not None:  # slice 10 D: nothing ran; a new card
        return Decision(call, gr, *changed)
    done = gr.outcome is GatewayOutcome.EXECUTED
    fallback = (
        f"Done, Sir: {action.summary}."
        if done
        else f"That did not go through: {gr.error or gr.outcome.value}."
    )
    return Decision(
        call,
        gr,
        fallback,
        "Owner approved this action; report the outcome in one sentence.",
        _chips(gateway, call, gr),
        made,
    )


def _chips(gateway: Gateway, call: ToolCall, gr: GatewayResult) -> tuple[UndoRef, ...]:
    """The Undo chip of an approved undo-able delete. Never raises: the call already ran, and
    bookkeeping after it must never relabel it as not done (slice 11 C review LOW-3)."""
    try:
        return tuple(undo_refs(gateway.registry, [call], [gr]))
    except Exception as exc:  # noqa: BLE001 — the chip is lost; the delete stays in the bin
        log.warning("no undo chip for an approved card", extra={"error": type(exc).__name__})
        return ()


async def declined(
    gateway: Gateway, call: ToolCall, action: PendingAction, approval_id: str
) -> Decision:
    if not await gateway.gate.cancel(approval_id):
        # approved (or declined) concurrently: never record a decline that didn't happen
        raise LookupError(f"no pending approval {approval_id} in this session")
    tool = gateway.registry.get(action.tool)
    entry = await gateway.audit.append(
        agent=tool.agent if tool else "gateway",
        tool=action.tool,
        risk=action.risk,
        outcome="declined",
        args=action.arguments,
    )
    await gateway.observe_declined(action, entry)  # R1 D7: the Activity view hears of it
    return Decision(
        call,
        GatewayResult(GatewayOutcome.DENIED, error="declined by owner"),
        "Understood, Sir. Nothing was sent or changed.",
        "Owner declined this action; acknowledge in one sentence, nothing was done.",
    )


__all__ = [
    "Decision",
    "Outcome",
    "approved",
    "declined",
    "narration",
    "record_exchange",
    "response",
    "single",
]
