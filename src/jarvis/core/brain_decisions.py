# src/jarvis/core/brain_decisions.py
"""The owner's approve / decline of a waiting action, before it is narrated (Layer 4).

Split out of `jarvis.core.brain` (slice 10 integration) so the core loop stays small; the Brain
still owns the order of events (`Brain._decide_locked`): run or cancel the action here, store
its tool exchange BEFORE any model call (`record_exchange` + `jarvis.core.saving`), then narrate.

- `approved`: runs the call through the gateway with the approval token. A lost race (the token
  is spent or expired) raises LookupError and touches nothing; a card that changed since the
  owner saw it (slice 10 D) is withdrawn and proposed again — nothing ran.
- `declined`: cancels the card (a concurrent decision raises LookupError, so a decline that did
  not happen is never recorded) and audits it.
"""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.core.guardrails import PendingAction
from jarvis.core.models import Session, Turn
from jarvis.llm.base import Role, TextBlock, ToolCall, ToolResultBlock
from jarvis.tools.gateway import Gateway, GatewayOutcome, GatewayResult


@dataclass(frozen=True)
class Decision:
    """What an owner's approve / decline produced, before it is narrated."""

    call: ToolCall
    result: GatewayResult
    fallback: str
    instruction: str


def record_exchange(session: Session, d: Decision, trace_id: str | None) -> list[Turn]:
    """The decided action as a tool exchange (tool_use → tool_result + instruction)."""
    result = ToolResultBlock(
        tool_use_id=d.call.id,
        content=d.result.for_model(),
        is_error=d.result.outcome is not GatewayOutcome.EXECUTED,
    )
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
    gateway: Gateway, call: ToolCall, action: PendingAction, approval_id: str, scope: str
) -> Decision:
    gr = await gateway.execute(call, confirmation_id=approval_id, scope=scope)
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
        call, gr, fallback, "Owner approved this action; report the outcome in one sentence."
    )


async def declined(
    gateway: Gateway, call: ToolCall, action: PendingAction, approval_id: str
) -> Decision:
    if not await gateway.gate.cancel(approval_id):
        # approved (or declined) concurrently: never record a decline that didn't happen
        raise LookupError(f"no pending approval {approval_id} in this session")
    tool = gateway.registry.get(action.tool)
    await gateway.audit.append(
        agent=tool.agent if tool else "gateway",
        tool=action.tool,
        risk=action.risk,
        outcome="declined",
        args=action.arguments,
    )
    return Decision(
        call,
        GatewayResult(GatewayOutcome.DENIED, error="declined by owner"),
        "Understood, Sir. Nothing was sent or changed.",
        "Owner declined this action; acknowledge in one sentence, nothing was done.",
    )


__all__ = ["Decision", "approved", "declined", "record_exchange"]
