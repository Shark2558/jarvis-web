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


class AskReason(StrEnum):
    """Why a call that could have run became a card (slice 11 review MEDIUM-1). Set by the gateway
    where an Allow is tightened to Ask; decides what Approve all may run (`PendingAction.bulk_ok`).
    """

    UNTRUSTED_CONTEXT = "untrusted_context"  # the model had read other people's words this round
    DRAFT_RECIPIENT = "draft_recipient"  # a draft to an address the owner did not type (D7 a)
    SPOKEN = "spoken"  # a spoken turn: anyone in the room may have said it
    OWNER_RULE = "owner_rule"  # an "Ask first" rule (the owner's, or the configured policy's)
    CAP = "cap"  # past the message's free undo-able deletes (slice 11 D3)
    RISK = "risk"  # can't be undone: always asks (R3)


# Memory writes are never approved in bulk: a note planted by someone else's words must be read by
# the owner one card at a time (slice 11 review MEDIUM-1).
MEMORY_TOOL_PREFIX = "memory_"


class PendingAction(BaseModel):
    id: str = Field(default_factory=lambda: secrets.token_urlsafe(12))
    tool: str
    arguments: dict[str, Any]
    risk: ActionRisk
    summary: str = Field(description="Plain-language 'this will…' shown to the owner")
    scope: str | None = Field(default=None, description="session/user the action belongs to")
    # Slice 10 D: `risk` is the gate's view (every card is confirm-before-commit, so it reads
    # IRREVERSIBLE); `tool_risk` is what the call itself can do. A passkey is asked for only when
    # it is IRREVERSIBLE — or unknown (a card stored before this field existed): fail safe.
    tool_risk: ActionRisk | None = Field(default=None, description="Risk of the call itself")
    reason: AskReason | None = Field(
        default=None, description="Why it asks (slice 11); None: a card stored before the field"
    )
    # Slice 11 D8: the round that proposed this card had read other people's content (a spoken-
    # only round doesn't count), so what it writes is marked as outside when it runs. Set by the
    # gateway at proposal; never part of what makes two cards the same. None: a card stored
    # before this field existed — the gateway treats it as outside (fail closed).
    outside: bool | None = None
    # R2 I1: the round that proposed this card was spoken (`taint.spoken_in_context`). Approved on
    # screen, outside that turn, it still runs as spoken (`ToolContext.spoken`), so a note or a
    # thing it writes records `voice` origin. Never part of what makes two cards the same.
    spoken: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime = Field(default_factory=lambda: datetime.now(UTC) + timedelta(minutes=10))

    @property
    def expired(self) -> bool:
        return datetime.now(UTC) > self.expires_at

    @property
    def irreversible(self) -> bool:
        """True when the call itself can't be undone (or its risk is unknown: fail safe)."""
        return self.tool_risk is None or self.tool_risk is ActionRisk.IRREVERSIBLE

    @property
    def bulk_ok(self) -> bool:
        """May Approve all run it? Never when it can't be undone (or its risk is unknown), never a
        draft to an address the owner did not type, never a memory write — whatever its reason,
        so also an old card without one. A calendar / reminder / to-do card made after reading a
        mail stays one tap: "add these 5 events from the email"."""
        if self.irreversible or self.reason is AskReason.DRAFT_RECIPIENT:
            return False
        return not self.tool.startswith(MEMORY_TOOL_PREFIX)


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


class TooManyApprovals(PermissionError):
    """A NEW card past this owner message's budget (`jarvis.tools.budget`): nothing is stored.
    (A proposal identical to a waiting card is not new and is never refused.)"""

    def __init__(self, action: PendingAction) -> None:
        super().__init__(f"too many approvals in one request: {action.summary}")
        self.action = action


ActionMatcher = Callable[[PendingAction], bool]


def carried_reason(stored: AskReason | None, fresh: AskReason | None) -> AskReason | None:
    """The reason a card keeps when the same call is proposed again: the old one, unless the new
    one is one-by-one by itself (RISK, DRAFT_RECIPIENT) or there was none (a card from before the
    field). A one-by-one card never turns bulk."""
    if fresh in (AskReason.RISK, AskReason.DRAFT_RECIPIENT) or stored is None:
        return fresh
    return stored


def same_card(stored: PendingAction, proposed: PendingAction) -> bool:
    """Is `proposed` exactly the action the owner saw on `stored`'s card? Same tool, arguments
    (drift → re-confirm) and conversation — and (slice 10 D) the same card text and the same
    risk of the call itself; a card stored before `tool_risk` existed matches any."""
    return (
        stored.tool == proposed.tool
        and stored.arguments == proposed.arguments
        and stored.scope == proposed.scope
        and stored.summary == proposed.summary
        and (stored.tool_risk is None or stored.tool_risk == proposed.tool_risk)
    )


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

    async def pending_in(self, scope: str | None) -> list[PendingAction]:
        """Unexpired actions of one conversation, oldest first: what a new proposal is checked
        against for a duplicate. A store that can query by scope overrides this, so a proposal
        never reads every waiting card (slice 10 integration review L4)."""
        return [a for a in await self.list_pending() if a.scope == scope]


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

    async def check(
        self,
        action: PendingAction,
        *,
        confirmation_id: str | None = None,
        new_allowed: bool = True,
    ) -> None:
        """Raise ConfirmationRequired unless the action is safe or explicitly confirmed.

        Without a token the action is stored and ConfirmationRequired raised — or, when it is not
        a duplicate and `new_allowed` is False (the message's card budget is spent),
        TooManyApprovals and nothing is stored. With a token it runs only if the store atomically
        consumes a matching, unexpired approval; otherwise ConfirmationInvalid — a wrong token
        never consumes another action's token and never stores anything."""
        if action.risk is not ActionRisk.IRREVERSIBLE:
            return

        def same(p: PendingAction) -> bool:
            return same_card(p, action)

        if confirmation_id is None:
            # the same proposal twice must not become two approvals (= two sends)
            existing = next((p for p in await self.store.pending_in(action.scope) if same(p)), None)
            if existing is not None:
                merged = {  # D8: outside is never forgotten; the stricter reason wins
                    "outside": True
                    if action.outside and existing.outside is False
                    else existing.outside,
                    "reason": carried_reason(existing.reason, action.reason),
                    "spoken": existing.spoken or action.spoken,  # R2: never forgotten either
                }
                if any(merged[k] != getattr(existing, k) for k in merged):
                    existing = existing.model_copy(update=merged)
                    await self.store.put(existing)
                raise ConfirmationRequired(existing)
            if not new_allowed:
                raise TooManyApprovals(action)
            await self.store.put(action)
            raise ConfirmationRequired(action)
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
