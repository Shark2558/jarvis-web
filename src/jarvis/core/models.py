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

from pydantic import BaseModel, Field, PrivateAttr

from jarvis.core.guardrails import PendingAction
from jarvis.llm.base import ContentBlock, Role, Usage
from jarvis.recall.models import MemoryRef


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
    channel: Literal["text", "voice"] = "text"


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
    channel: Literal["text", "voice"] = Field(
        default="text",
        description="voice: the owner spoke this message and the reply will be read aloud "
        "(short, plain spoken answer; slice 9 D7)",
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


class SessionSummary(BaseModel):
    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    turn_count: int
    total_cost_usd: float
    total_cost_inr: float = Field(default=0.0, description="≈ rupees at today's rate")
    title: str = Field(default="", description="First words of the owner's first message")


class SessionView(Session):
    """GET /v1/sessions/{id}: the stored conversation plus its cost in rupees (display only;
    the stored record keeps USD, the provider's unit)."""

    total_cost_inr: float = 0.0


TITLE_MAX_CHARS = 80


def session_title(s: Session) -> str:
    first = next((t.content for t in s.turns if t.role is Role.USER and t.content.strip()), "")
    text = " ".join(first.split())
    return text if len(text) <= TITLE_MAX_CHARS else text[: TITLE_MAX_CHARS - 1].rstrip() + "…"
