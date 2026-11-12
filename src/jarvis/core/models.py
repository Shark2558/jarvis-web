# src/jarvis/core/models.py
"""Core data model for Phase 0: sessions and turns.

Layer 3 (Context & Orchestration) + Layer 7 (Data). In Phase 3 turns are additionally
embedded into the vector store; the shape below is the row that gets embedded, so keep it
stable.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from jarvis.core.guardrails import PendingAction
from jarvis.documents.models import AttachmentRef
from jarvis.llm.base import ContentBlock, Role, Usage
from jarvis.recall.models import MemoryRef
from jarvis.tools.reply_cards import ReplyCard, WhatsAppCard
from jarvis.undo.models import UndoRef as UndoRef  # re-exported: replies carry it (slice 11)
from jarvis.web.sources import Source as Source  # re-exported: replies and turns carry it

HEARD_LIMIT = 2_000  # R11.1 D8: the heard words of one spoken message


def _now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


class Turn(BaseModel):
    id: str = Field(default_factory=lambda: new_id("turn"))
    role: Role
    content: str
    # tool_use / tool_result exchanges are kept as blocks so the window can replay them
    blocks: list[ContentBlock] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    trace_id: str | None = None
    # populated on assistant turns only
    model: str | None = None
    usage: Usage | None = None
    cost_usd: float = 0.0
    latency_ms: int | None = None
    # produced from a tool or approval outcome (an approval's narration, a reply written after
    # tool rounds): private data, never sent to a brain that may train on content
    tool_derived: bool = False
    # how an owner message arrived (slice 9): "voice" was heard through the microphone, so it
    # may be someone else's words — never used for memory learning (jarvis.recall.learning)
    channel: Literal["text", "voice", "telegram"] = "text"
    # R1: the fallback brain on the owner's laptop wrote this reply (llm.fallback)
    offline: bool = False
    # web sources this reply cited as [n] (slice 10 B), from the conversation's stored results
    sources: list[Source] = Field(default_factory=list)
    # files sent with an owner message (slice 10 E): names and counts only. Their start travels
    # as a second, fenced text block; a turn with blocks never reaches a training brain.
    attachments: list[AttachmentRef] = Field(default_factory=list)
    # R11.1 D8: what the microphone heard, when JARVIS understood a spoken message as something
    # else (`content` is what it understood and acted on). Shown as "heard / understood as"; it is
    # never sent to a model and never learned from. None: nothing was corrected.
    heard: str | None = Field(default=None, max_length=HEARD_LIMIT)


class Session(BaseModel):
    id: str = Field(default_factory=lambda: new_id("sess"))
    user_id: str
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    turns: list[Turn] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    # running totals so a dashboard never has to replay turns
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    # Storage bookkeeping, never serialised: the stored revision this copy was read at or last
    # saved as (the session store's compare-and-set, slice 10). Opaque outside the store.
    _store_mark: Any = PrivateAttr(default=None)

    def append(self, turn: Turn) -> None:
        self.turns.append(turn)
        self.updated_at = _now()
        if turn.usage:
            self.total_input_tokens += turn.usage.input_tokens
            self.total_output_tokens += turn.usage.output_tokens
        self.total_cost_usd = round(self.total_cost_usd + turn.cost_usd, 6)


# ---- API contracts -------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = Field(
        default=None, description="Omit to start a new session; the response returns its id"
    )
    user_id: str = Field(default="owner", description="Single-user system until Phase 6")
    tier: str | None = Field(
        default=None, description="fast | balanced | strong (default from config)"
    )
    brain: str | None = Field(
        default=None,
        max_length=64,
        description="Brain id from GET /v1/brains. Omit to keep the session's brain (or the "
        "default). The choice is remembered on the session.",
    )
    channel: Literal["text", "voice", "telegram"] = Field(
        default="text",
        description="voice: the owner spoke this message and the reply will be read aloud "
        "(short, plain spoken answer; slice 9 D7). telegram: set only by the Telegram service; "
        "the HTTP chat routes refuse it (R1)",
    )
    attachments: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Ids from POST /v1/attachments sent with this message (at most 10; R11.1 D11)",
    )
    heard: str | None = Field(
        default=None,
        max_length=HEARD_LIMIT,
        description="R11.1 D8: the recogniser's own words, when `message` is the corrected "
        "reading of a spoken message; kept with the turn for display only",
    )


class PendingApproval(BaseModel):
    id: str
    tool: str
    summary: str
    arguments: dict[str, Any]
    risk: str
    expires_at: datetime
    session_id: str | None = Field(
        default=None, description="Conversation the action belongs to (approve from there)"
    )
    tool_risk: str | None = Field(
        default=None, description="What the call itself can do (slice 10 D); risk is the gate's"
    )
    passkey_required: bool = Field(
        default=False, description="Approving needs a passkey check (GET /v1/approvals sets it)"
    )
    reason: str | None = Field(default=None, description="Why it asks (slice 11; None: unknown)")
    bulk_ok: bool = Field(
        default=False, description="Approve all may run it (else: its own card, one by one)"
    )

    @classmethod
    def from_action(cls, a: PendingAction) -> PendingApproval:
        sid = a.scope.rsplit(":", 1)[1] if a.scope and ":" in a.scope else None
        return cls(
            id=a.id,
            tool=a.tool,
            summary=a.summary,
            arguments=a.arguments,
            risk=a.risk.value,
            expires_at=a.expires_at,
            session_id=sid,
            tool_risk=a.tool_risk.value if a.tool_risk is not None else None,
            reason=a.reason.value if a.reason is not None else None,
            bulk_ok=a.bulk_ok,
        )


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    tool_calls: int = 0
    pending_approvals: list[PendingApproval] = Field(default_factory=list)
    trace_id: str
    model: str
    brain: str = Field(default="", description="Which brain answered")
    usage: Usage
    cost_usd: float
    cost_inr: float = Field(default=0.0, description="This reply, ≈ rupees at today's rate")
    total_cost_usd: float = Field(default=0.0, description="The whole conversation so far")
    total_cost_inr: float = Field(default=0.0, description="The whole conversation, ≈ rupees")
    latency_ms: int
    turn_count: int
    memory_used: list[MemoryRef] = Field(
        default_factory=list, description="Notes about the owner sent with this reply"
    )
    offline: bool = Field(default=False, description="R1: answered by the owner's laptop")
    sources: list[Source] = Field(
        default_factory=list,
        description="Web sources the reply cited as [n] (only stored search results)",
    )
    undo: list[UndoRef] = Field(
        default_factory=list,
        description="Deletes this reply made that can be undone (the console's Undo chip; "
        "POST /v1/deleted/{undo_id}/restore)",
    )
    cards: list[ReplyCard] = Field(
        default_factory=list,
        description="Slice 12: place, route and video cards from this reply's Maps / YouTube "
        "results (Google links and attribution) and WhatsApp drafts (kind 'whatsapp': Open in "
        "WhatsApp; nothing was sent) and, R11, an approved UPI payment (kind 'upi': its upi://pay "
        "link and QR, shown once). Never stored; a reopened conversation gets only its "
        "WhatsApp drafts back (GET /v1/sessions/{id} drafts)",
    )


class SessionSummary(BaseModel):
    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    turn_count: int
    total_cost_usd: float
    total_cost_inr: float = Field(default=0.0, description="≈ rupees at today's rate")
    title: str = Field(default="", description="First words of the owner's first message")


class StoredDraft(BaseModel):
    """A WhatsApp draft card rebuilt for a conversation opened again (`jarvis.whatsapp.restore`)
    and the index in `turns` of the reply it belongs under."""

    model_config = ConfigDict(frozen=True)

    turn: int
    card: WhatsAppCard


class SessionView(Session):
    """GET /v1/sessions/{id}: the stored conversation plus its cost in rupees (display only;
    the stored record keeps USD, the provider's unit) and its WhatsApp draft cards, rebuilt from
    the stored draft results and checked again (final review; never Maps / YouTube cards)."""

    total_cost_inr: float = 0.0
    drafts: list[StoredDraft] = Field(
        default_factory=list,
        description="WhatsApp draft cards (Open in WhatsApp), each under the reply at `turn`",
    )


TITLE_MAX_CHARS = 80


def session_title(s: Session) -> str:
    first = next((t.content for t in s.turns if t.role is Role.USER and t.content.strip()), "")
    text = " ".join(first.split())
    return text if len(text) <= TITLE_MAX_CHARS else text[: TITLE_MAX_CHARS - 1].rstrip() + "…"
