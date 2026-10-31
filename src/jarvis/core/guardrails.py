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

import asyncio
import re
import secrets
from abc import ABC, abstractmethod
from collections.abc import Callable
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
    scope: str | None = Field(default=None, description="session/user the action belongs to")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime = Field(default_factory=lambda: datetime.now(UTC) + timedelta(minutes=10))

    @property
    def expired(self) -> bool:
        return datetime.now(UTC) > self.expires_at


class ConfirmationRequired(PermissionError):
    def __init__(self, action: PendingAction) -> None:
        super().__init__(f"confirmation required: {action.summary}")
        self.action = action


class ConfirmationInvalid(PermissionError):
    """A confirmation token was spent, expired, unknown, or for different arguments/scope.
    Nothing runs and nothing new is stored: a stale token must never re-create an approval
    (that is how a double click could otherwise send twice)."""

    def __init__(self, action: PendingAction) -> None:
        super().__init__(f"confirmation no longer valid: {action.summary}")
        self.action = action


ActionMatcher = Callable[[PendingAction], bool]


class ApprovalStore(ABC):
    """Where actions awaiting owner approval live (Layer 7). Must survive restarts in prod."""

    @abstractmethod
    async def put(self, action: PendingAction) -> None: ...

    @abstractmethod
    async def get(self, approval_id: str) -> PendingAction | None: ...

    @abstractmethod
    async def consume(self, approval_id: str, matches: ActionMatcher) -> PendingAction | None:
        """Atomically remove and return the action iff it exists, is unexpired and `matches`.
        Otherwise leave it untouched and return None (a wrong token never consumes it)."""

    @abstractmethod
    async def cancel(self, approval_id: str) -> PendingAction | None:
        """Remove and return the action, or None if it was already gone."""

    @abstractmethod
    async def list_pending(self) -> list[PendingAction]:
        """Unexpired actions, oldest first."""


class InMemoryApprovalStore(ApprovalStore):
    """Process-local. Dev, tests, and the redis/memory session backends."""

    def __init__(self) -> None:
        self._pending: dict[str, PendingAction] = {}
        self._lock = asyncio.Lock()

    async def put(self, action: PendingAction) -> None:
        async with self._lock:
            self._pending[action.id] = action.model_copy(deep=True)

    async def get(self, approval_id: str) -> PendingAction | None:
        a = self._pending.get(approval_id)
        return a.model_copy(deep=True) if a else None

    async def consume(self, approval_id: str, matches: ActionMatcher) -> PendingAction | None:
        async with self._lock:
            a = self._pending.get(approval_id)
            if a is None or a.expired or not matches(a):
                return None
            return self._pending.pop(approval_id)

    async def cancel(self, approval_id: str) -> PendingAction | None:
        async with self._lock:
            return self._pending.pop(approval_id, None)

    async def list_pending(self) -> list[PendingAction]:
        async with self._lock:
            self._pending = {k: v for k, v in self._pending.items() if not v.expired}
            live = sorted(self._pending.values(), key=lambda a: a.created_at)
            return [a.model_copy(deep=True) for a in live]


class ConfirmationGate:
    """Confirm-before-commit for IRREVERSIBLE actions; storage is pluggable."""

    def __init__(self, store: ApprovalStore | None = None) -> None:
        self.store: ApprovalStore = store or InMemoryApprovalStore()

    async def check(self, action: PendingAction, *, confirmation_id: str | None = None) -> None:
        """Raise ConfirmationRequired unless the action is safe or explicitly confirmed.

        Without a token the action is stored and ConfirmationRequired raised. With a token it
        runs only if the store atomically consumes a matching, unexpired approval; otherwise
        ConfirmationInvalid — a wrong token never consumes another action's token and never
        stores anything."""
        if action.risk is not ActionRisk.IRREVERSIBLE:
            return
        if confirmation_id is None:
            await self.store.put(action)
            raise ConfirmationRequired(action)

        def same(p: PendingAction) -> bool:
            return (
                p.tool == action.tool
                and p.arguments == action.arguments  # argument drift → re-confirm
                and p.scope == action.scope
            )

        if await self.store.consume(confirmation_id, same) is None:
            raise ConfirmationInvalid(action)

    async def get(self, confirmation_id: str) -> PendingAction | None:
        a = await self.store.get(confirmation_id)
        return None if a is None or a.expired else a

    async def cancel(self, confirmation_id: str) -> bool:
        return await self.store.cancel(confirmation_id) is not None

    async def pending(self) -> list[PendingAction]:
        return await self.store.list_pending()

    async def cancel_scope(self, scope: str) -> int:
        """Drop every waiting approval of one conversation (used when it is deleted)."""
        n = 0
        for a in await self.store.list_pending():
            if a.scope == scope and await self.store.cancel(a.id) is not None:
                n += 1
        return n
