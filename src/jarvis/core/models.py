# src/jarvis/core/models.py
"""Core data model for Phase 0: sessions and turns.

Layer 3 (Context & Orchestration) + Layer 7 (Data). In Phase 3 turns are additionally
embedded into the vector store; the shape below is the row that gets embedded, so keep it
stable.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from jarvis.llm.base import ContentBlock, Role, Usage


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
    confirmation_id: str | None = Field(
        default=None, description="Internal: set when resuming an approved action"
    )


class PendingApproval(BaseModel):
    id: str
    tool: str
    summary: str
    arguments: dict[str, Any]
    risk: str
    expires_at: datetime


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    tool_calls: int = 0
    pending_approvals: list[PendingApproval] = Field(default_factory=list)
    trace_id: str
    model: str
    usage: Usage
    cost_usd: float
    latency_ms: int
    turn_count: int


class SessionSummary(BaseModel):
    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    turn_count: int
    total_cost_usd: float
