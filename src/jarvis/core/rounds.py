# src/jarvis/core/rounds.py
"""Storing one owner message's tool rounds when another window may change the conversation
(slice 10 integration review M1; Layer 3).

Until a call that changes something has run, a round is stored with a plain save: a conflict
there is the ordinary 409 ("your message was kept") and a retry repeats only look-ups. From the
first round in which a write ran (a to-do, an event, a draft — anything above read-only), the
change has already happened outside JARVIS, so a 409 would make the owner send again and do it
twice. Those rounds — and every later save of the same message, its reply included — go through
the conflict-safe path approve / decline use (`jarvis.core.saving.record_after_action`): reload,
re-append this message's unsaved turns once, never raise. If even that fails the tool loop stops
(no further tool runs in a conversation that can't record them), the reply says in plain words
what was done, and the response notes that it could not be recorded.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from jarvis.core.guardrails import ActionRisk
from jarvis.core.models import PendingApproval, Session, Turn, UndoRef
from jarvis.core.saving import not_recorded_note, record_after_action
from jarvis.llm.base import Completion, ContentBlock, Role, TextBlock, ToolCall, Usage
from jarvis.memory.base import SessionStore
from jarvis.tools.gateway import GatewayOutcome, GatewayResult
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.reply_cards import AnyCard


def request_turn(completion: Completion) -> tuple[Turn, list[ContentBlock]]:
    """The model's tool request as a block turn (its words, then its calls), and those blocks."""
    text = completion.text
    blocks: list[ContentBlock] = [TextBlock(text=text)] if text.strip() else []
    blocks += completion.tool_calls
    turn = Turn(
        role=Role.ASSISTANT,
        content=text,
        blocks=blocks,
        model=completion.model,
        usage=completion.usage,
        cost_usd=completion.cost_usd,
        latency_ms=completion.latency_ms,
    )
    return turn, blocks


def undo_refs(
    registry: ToolRegistry, calls: Sequence[ToolCall], results: Sequence[GatewayResult]
) -> list[UndoRef]:
    """The undo-able deletes among calls that ran (slice 11: the reply's Undo chips) — only
    from tools marked undoable, so a result that merely looks like one never makes a chip."""
    out: list[UndoRef] = []
    for call, gr in zip(calls, results, strict=True):
        tool = registry.get(call.name)
        if gr.outcome is not GatewayOutcome.EXECUTED or tool is None or not tool.undoable:
            continue
        if (ref := UndoRef.from_result(gr.result)) is not None:
            out.append(ref)
    return out


MAY_NOT_BE_DONE = "(may not have been done)"


@dataclass
class Rounds:
    """One owner message's tool rounds: the session to continue with (a reload replaces it), how
    many rounds ran, how many calls ran in them without raising (`ran`: R11.1 D2's "I did N
    steps") and how many failed (`failed`: the tool raised, or its arguments were refused), what
    changed something (card-style summaries), the undo-able deletes among them, and turns not
    yet stored."""

    session: Session
    count: int = 0
    ran: int = 0
    failed: int = 0
    done: list[str] = field(default_factory=list)
    unrecorded: list[Turn] = field(default_factory=list)
    undo: list[UndoRef] = field(default_factory=list)
    # slice 12: place / route / video / WhatsApp draft cards the message's tools made for the
    # owner's screen (`jarvis.tools.reply_cards`); shown with the reply, never stored
    cards: list[AnyCard] = field(default_factory=list)

    @property
    def wrote(self) -> bool:
        return bool(self.done)

    def note(
        self, registry: ToolRegistry, calls: Sequence[ToolCall], results: Sequence[GatewayResult]
    ) -> None:
        """Remember each call of this round that ran and can change something. A tool that
        raised ran too — it may have written before it failed — and is noted as such."""
        self.undo += undo_refs(registry, calls, results)
        for call, gr in zip(calls, results, strict=True):
            self.failed += int(gr.outcome is GatewayOutcome.ERROR)
            if not gr.ran:
                continue
            self.ran += int(not gr.raised)
            tool = registry.get(call.name)
            if tool is not None and tool.effective_risk(call.arguments) is not ActionRisk.READ_ONLY:
                said = tool.summary(call.arguments)
                self.done.append(said if not gr.raised else f"{said} {MAY_NOT_BE_DONE}")

    def opened(self, completion: Completion) -> tuple[Turn, list[ContentBlock]]:
        """A round begins: the model's tool request is appended as a block turn."""
        self.count += 1
        turn, blocks = request_turn(completion)
        self.session.append(turn)
        return turn, blocks

    def closed(
        self, registry: ToolRegistry, calls: Sequence[ToolCall], outcomes: Sequence[GatewayResult]
    ) -> tuple[Turn, list[ContentBlock], list[PendingApproval]]:
        """A round's results: one block turn (trusted only by the gateway, slice 11 D8), noted,
        and the approvals they left waiting."""
        results: list[ContentBlock] = [
            gr.block(call.id) for call, gr in zip(calls, outcomes, strict=True)
        ]
        done = Turn(role=Role.USER, content="", blocks=results)
        self.session.append(done)
        self.note(registry, calls, outcomes)
        waiting = [
            PendingApproval.from_action(gr.pending)
            for gr in outcomes
            if gr.outcome is GatewayOutcome.AWAITING_CONFIRMATION and gr.pending
        ]
        return done, results, waiting

    async def store(self, store: SessionStore, turns: Sequence[Turn]) -> bool:
        """Store `self.session`, whose last `turns` were just appended. Before any write: a plain
        save (SessionConflict propagates). After one: conflict-safe, never raises; False when the
        turns (and any earlier unrecorded ones) could not be stored."""
        if not self.wrote:
            await store.save(self.session)
            return True
        pending = [*self.unrecorded, *turns]
        self.session, recorded = await record_after_action(store, self.session, pending)
        self.unrecorded = [] if recorded else pending
        return recorded

    def stopped(self, last: Completion) -> Completion:
        """The reply when a round that changed something could not be recorded: what was done,
        in plain words (no model call: nothing more runs in a conversation that can't record)."""
        return last.model_copy(
            update={
                "text": f"Done, Sir: {'; '.join(self.done)}.",
                "tool_calls": [],
                "usage": Usage(),
                "cost_usd": 0.0,  # that call's cost is on the round's turn already
                "latency_ms": 0,
            }
        )

    def reply_note(self, stored: bool) -> str:
        """Added to the response (never stored) when the message's record is incomplete."""
        return "" if stored or not self.wrote else " " + not_recorded_note(True)


__all__ = ["Rounds", "undo_refs"]
