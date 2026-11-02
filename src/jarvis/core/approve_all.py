# src/jarvis/core/approve_all.py
"""Approve all (slice 11 D6; Layer 4): several waiting cards approved with one tap.

Only the cards the owner listed (at most `MAX_IDS`), in the order listed (a repeated id counts
once), and only those whose call can be undone — R2, or an R1 call the owner set to "Ask first".
Each runs exactly as a single approval would (`brain_decisions.approved`: the gateway looks at
the call again; a card that changed since it was proposed — e.g. an event that gained guests and
so became irreversible — is withdrawn and proposed again, and nothing runs), and its tool exchange
is stored right after it, before the next card and before any model call.

Never here: a card whose call can't be undone (R3, or a card of unknown risk: fail safe). It stays
waiting for its own approval and passkey, and the reply says so. Approve all carries no passkey at
all (the route presents none), so even a card that slipped through would meet the approval guard.

A card that is not waiting in THIS conversation (another conversation's, decided, expired,
unknown) is reported and not run. One card failing — the tool erred, or approving it raised — is
reported and the others still run. Only a conversation that can't record what ran stops the batch,
as the tool loop does (`jarvis.core.rounds`): the cards after it are reported as not approved.

The reply: each exchange tells the model the card was approved with Approve all, and the model
narrates the whole batch ONCE (`Brain._narrated`, one model call; plainly when it can't). Cards
that never reached an exchange (skipped, not found, errors) are added as a fixed sentence.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from jarvis.core import brain_decisions as decisions
from jarvis.core.guardrails import PendingAction
from jarvis.core.models import ChatResponse, PendingApproval, Session, Turn, UndoRef
from jarvis.core.rounds import undo_refs
from jarvis.core.saving import record_after_action
from jarvis.llm.base import ToolCall
from jarvis.logging import get_logger
from jarvis.memory.base import SessionStore
from jarvis.tools.card import one_line
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.web.ledger import web_conversation

log = get_logger(__name__)

MAX_IDS = 20
ID_LIMIT = 64
LINE_LIMIT = 120
ApprovalId = Annotated[str, StringConstraints(min_length=1, max_length=ID_LIMIT)]

INSTRUCTION = (
    "The owner approved this together with other waiting actions (Approve all). Report the "
    "outcomes of all of them together, in one or two sentences."
)
NOTHING = "Nothing was approved, Sir."
NOT_WAITING = "Not waiting any more (already decided, expired, or not in this conversation)."
ONE_AT_A_TIME = (
    "Can't be undone, so it needs its own approval (and your passkey, when you require one): "
    "approve it on its own card."
)
COULD_NOT = "Could not be approved just now, so nothing was done. Try it on its own card."
NOT_RECORDED = (
    "Not approved: this conversation could not record what was done, so Approve all stopped. "
    "Approve it again."
)
CHANGED = "Changed since you saw it, so nothing was done. A new approval is waiting."


class CardStatus(StrEnum):
    DONE = "done"  # ran
    FAILED = "failed"  # approved, but did not go through (the tool failed, or a rule blocks it)
    CHANGED = "changed"  # withdrawn and proposed again; nothing ran
    NEEDS_PASSKEY = "needs_passkey"  # can't be undone: never run here, still waiting
    NOT_FOUND = "not_found"  # not waiting in this conversation
    ERROR = "error"  # approving it raised; nothing was done
    NOT_RUN = "not_run"  # the batch stopped before it (the conversation can't record)


class CardResult(BaseModel):
    id: str
    status: CardStatus
    tool: str = ""
    summary: str = Field(default="", description="The card as the owner saw it")
    detail: str = Field(default="", description="Plain words when it did not simply run")
    new_approval: PendingApproval | None = Field(
        default=None, description="status changed: the card waiting now"
    )


class ApproveAllResponse(ChatResponse):
    results: list[CardResult] = Field(default_factory=list, description="One per id, in order")


_NARRATED = (CardStatus.DONE, CardStatus.FAILED, CardStatus.CHANGED)


@dataclass
class Batch:
    """One Approve all: the conversation to continue with (a reload replaces it) and results."""

    session: Session
    scope: str
    trace_id: str
    results: list[CardResult] = field(default_factory=list)
    unrecorded: list[Turn] = field(default_factory=list)
    again: list[PendingAction] = field(default_factory=list)
    ran: int = 0  # approved calls that went to their tool (done or failed)
    stopped: bool = False
    undo: list[UndoRef] = field(default_factory=list)  # undo-able deletes that ran: Undo chips

    def outcome(self) -> decisions.Outcome:
        narrated = [r for r in self.results if r.status in _NARRATED]
        return decisions.Outcome(
            fallback=" ".join(_said(r) for r in narrated) or NOTHING,
            unrecorded=list(self.unrecorded),
            did=self.ran > 0,
            tool_calls=self.ran,
            again=list(self.again),
            note=_note(self.results),
            narrate=bool(narrated),
            undo=list(self.undo),
        )


def distinct(ids: Sequence[str]) -> list[str]:
    """The ids in the order listed, each once."""
    return list(dict.fromkeys(ids))


def _line(summary: str) -> str:
    return one_line(summary.splitlines()[0] if summary else "", LINE_LIMIT) or "that action"


def _said(r: CardResult) -> str:
    if r.status is CardStatus.DONE:
        return f"Done, Sir: {_line(r.summary)}."
    return f"{_line(r.summary)}: {r.detail}"


def _count(n: int, one: str, many: str) -> str:
    return f"1 {one}" if n == 1 else f"{n} {many}"


def _note(results: list[CardResult]) -> str:
    """Fixed sentences for the cards the model was not told about."""
    by = {s: sum(1 for r in results if r.status is s) for s in CardStatus}
    parts: list[str] = []
    if n := by[CardStatus.NEEDS_PASSKEY]:
        what = _count(n, "action that can't be undone is", "actions that can't be undone are")
        parts.append(f"{what} still waiting: approve {'it' if n == 1 else 'each'} on its own card.")
    if n := by[CardStatus.NOT_FOUND]:
        parts.append(f"{_count(n, 'card was', 'cards were')} no longer waiting.")
    if n := by[CardStatus.ERROR]:
        parts.append(f"{_count(n, 'card', 'cards')} could not be approved just now; nothing was "
                     "done for them.")  # fmt: skip
    if n := by[CardStatus.NOT_RUN]:
        parts.append(f"{_count(n, 'card was', 'cards were')} not approved because this "
                     "conversation could not record it; approve again.")  # fmt: skip
    return " ".join(parts)


def _card(action: PendingAction, status: CardStatus, detail: str = "") -> CardResult:
    return CardResult(
        id=action.id, status=status, tool=action.tool, summary=action.summary, detail=detail
    )


def _decided(action: PendingAction, d: decisions.Decision) -> CardResult:
    if d.result.pending is not None:
        again = PendingApproval.from_action(d.result.pending)
        return _card(action, CardStatus.CHANGED, CHANGED).model_copy(update={"new_approval": again})
    if d.result.outcome is GatewayOutcome.EXECUTED:
        return _card(action, CardStatus.DONE)
    why = one_line(d.result.error or d.result.outcome.value, 200)
    return _card(action, CardStatus.FAILED, f"did not go through: {why}.")


async def _approve(gateway: Gateway, action: PendingAction, batch: Batch) -> decisions.Decision:
    call = ToolCall(id=f"approve_{action.id}", name=action.tool, arguments=action.arguments)
    with web_conversation(batch.session):
        d = await decisions.approved(gateway, call, action, action.id, batch.scope)
    return d if d.result.pending is not None else replace(d, instruction=INSTRUCTION)


async def _one(gateway: Gateway, store: SessionStore, batch: Batch, aid: str) -> CardResult:
    """One listed card: skipped, or approved and its exchange stored."""
    action = await gateway.gate.get(aid)
    if action is None or action.scope != batch.scope:
        return CardResult(id=aid, status=CardStatus.NOT_FOUND, detail=NOT_WAITING)
    if action.irreversible:  # R3 or unknown: its own approval and passkey, never a batch
        return _card(action, CardStatus.NEEDS_PASSKEY, ONE_AT_A_TIME)
    try:
        d = await _approve(gateway, action, batch)
    except LookupError:  # decided or expired meanwhile: nothing ran
        return _card(action, CardStatus.NOT_FOUND, NOT_WAITING)
    except Exception as exc:  # noqa: BLE001 — reported; the gateway runs no tool before raising
        log.warning("approve all: a card could not be approved",
                    extra={"tool": action.tool, "error": type(exc).__name__})  # fmt: skip
        return _card(action, CardStatus.ERROR, COULD_NOT)
    exchange = decisions.record_exchange(batch.session, d, batch.trace_id)
    batch.session, stored = await record_after_action(store, batch.session, exchange)
    batch.unrecorded, batch.stopped = ([] if stored else exchange), not stored
    if d.result.pending is not None:
        batch.again.append(d.result.pending)
    else:
        batch.ran += 1
    batch.undo += undo_refs([d.result])
    return _decided(action, d)


async def run(
    gateway: Gateway,
    store: SessionStore,
    session: Session,
    ids: Sequence[str],
    *,
    scope: str,
    trace_id: str,
) -> Batch:
    """Approve the listed cards that can be undone, one by one; see the module docstring."""
    batch = Batch(session=session, scope=scope, trace_id=trace_id)
    for aid in distinct(ids)[:MAX_IDS]:
        if batch.stopped:
            batch.results.append(CardResult(id=aid, status=CardStatus.NOT_RUN, detail=NOT_RECORDED))
            continue
        try:
            batch.results.append(await _one(gateway, store, batch, aid))
        except Exception as exc:  # noqa: BLE001 — one card never stops the others
            log.warning("approve all: a card could not be approved",
                        extra={"error": type(exc).__name__})  # fmt: skip
            batch.results.append(CardResult(id=aid, status=CardStatus.ERROR, detail=COULD_NOT))
    return batch


def response(resp: ChatResponse, results: list[CardResult]) -> ApproveAllResponse:
    return ApproveAllResponse.model_validate({**dict(resp), "results": results})


__all__ = [
    "MAX_IDS",
    "ApprovalId",
    "ApproveAllResponse",
    "Batch",
    "CardResult",
    "CardStatus",
    "distinct",
    "response",
    "run",
]
