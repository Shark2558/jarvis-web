# src/jarvis/core/guardrails.py
"""Safety & Guardrails (Layer 4).

Phase 0 ships two things:
1. Input guard — size cap and control-character scrub on every user turn.
2. The confirmation-gate *contract* (ActionRisk, PendingAction, ConfirmationGate) so that
   Phase 2 tools plug into an enforced interface instead of bolting one on later.
   No tool exists yet, so no action can reach the gate — but the tests prove the gate
   refuses to execute an IRREVERSIBLE action without a matching confirmation token.
"""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class InputRejected(ValueError):
    pass


def guard_input(text: str, *, max_chars: int) -> str:
    cleaned = _CONTROL_CHARS.sub("", text).strip()
    if not cleaned:
        raise InputRejected("empty message")
    if len(cleaned) > max_chars:
        raise InputRejected(f"message exceeds {max_chars} characters")
    return cleaned


# ---- confirm-before-commit contract ---------------------------------------------------------


class ActionRisk(StrEnum):
    READ_ONLY = "read_only"  # search, read calendar, list files
    REVERSIBLE = "reversible"  # create draft, add reminder, write scratch file
    IRREVERSIBLE = "irreversible"  # send, pay, delete, publish — always confirm


class PendingAction(BaseModel):
    id: str = Field(default_factory=lambda: secrets.token_urlsafe(12))
    tool: str
    arguments: dict[str, Any]
    risk: ActionRisk
    summary: str = Field(description="Plain-language 'this will…' shown to the owner")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime = Field(default_factory=lambda: datetime.now(UTC) + timedelta(minutes=10))

    @property
    def expired(self) -> bool:
        return datetime.now(UTC) > self.expires_at


class ConfirmationRequired(PermissionError):
    def __init__(self, action: PendingAction) -> None:
        super().__init__(f"confirmation required: {action.summary}")
        self.action = action


class ConfirmationGate:
    """In-memory registry of actions awaiting owner approval. Redis-backed in Phase 2."""

    def __init__(self) -> None:
        self._pending: dict[str, PendingAction] = {}

    def check(self, action: PendingAction, *, confirmation_id: str | None = None) -> None:
        """Raise ConfirmationRequired unless the action is safe or explicitly confirmed."""
        if action.risk is not ActionRisk.IRREVERSIBLE:
            return
        if confirmation_id is None:
            self._pending[action.id] = action
            raise ConfirmationRequired(action)
        pending = self._pending.pop(confirmation_id, None)
        if pending is None or pending.expired or pending.tool != action.tool:
            raise ConfirmationRequired(action)
        # confirmed: argument drift between prompt and execution is a classic agentic bug
        if pending.arguments != action.arguments:
            self._pending[action.id] = action
            raise ConfirmationRequired(action)

    def cancel(self, confirmation_id: str) -> bool:
        return self._pending.pop(confirmation_id, None) is not None

    def pending(self) -> list[PendingAction]:
        self._pending = {k: v for k, v in self._pending.items() if not v.expired}
        return list(self._pending.values())
