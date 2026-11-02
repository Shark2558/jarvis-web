# src/jarvis/tools/context.py
"""Who a tool is running for (Layer 3 → 6).

`Gateway.execute(call, scope="<user_id>:<session_id>")` sets a `ToolContext` contextvar around
`tool.run`, so connectors (Google tools) can look up the owner's credentials without the `Tool`
signature carrying a user id — and without a tool being able to pick a different user.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from jarvis.core.guardrails import ActionRisk

_RANK = {ActionRisk.READ_ONLY: 0, ActionRisk.REVERSIBLE: 1, ActionRisk.IRREVERSIBLE: 2}


@dataclass(frozen=True)
class ToolContext:
    user_id: str
    session_id: str | None
    scope: str
    # Slice 11: True while a call the owner approved on a card runs (the gateway spent its token).
    # A delete that finds the item changed since the decision (now shared) refuses unless approved.
    confirmed: bool = False
    # Slice 11 fix: the risk the gateway decided on (an approved card's risk; None outside the
    # gateway). A tool that finds MORE at run time (a solo event that gained guests) refuses: an
    # approved R2 card never runs an R3 delete.
    approved_risk: ActionRisk | None = None
    # Slice 11 D8: this call's content may carry other people's words (its round, or the round
    # that proposed its card, had read outside content): what it writes is marked as outside.
    outside: bool = False

    @classmethod
    def from_scope(
        cls,
        scope: str,
        *,
        confirmed: bool = False,
        approved_risk: ActionRisk | None = None,
        outside: bool = False,
    ) -> ToolContext:
        user_id, _, session_id = scope.partition(":")
        return cls(
            user_id=user_id,
            session_id=session_id or None,
            scope=scope,
            confirmed=confirmed,
            approved_risk=approved_risk,
            outside=outside,
        )

    def allows(self, live: ActionRisk) -> bool:
        """May the call do what it can do NOW (`live`)? Not more than was approved; outside the
        gateway's decision, an irreversible step only on an approved card."""
        if self.approved_risk is None:
            return live is not ActionRisk.IRREVERSIBLE or self.confirmed
        return _RANK[live] <= _RANK[self.approved_risk]


_current: contextvars.ContextVar[ToolContext | None] = contextvars.ContextVar(
    "jarvis_tool_context", default=None
)


def current_tool_context() -> ToolContext | None:
    """The context of the tool call in flight, or None outside the gateway."""
    return _current.get()


def require_tool_context() -> ToolContext:
    ctx = _current.get()
    if ctx is None:
        raise RuntimeError("tool invoked outside the gateway: no owner context")
    return ctx


@contextmanager
def tool_context(
    scope: str | None,
    *,
    confirmed: bool = False,
    approved_risk: ActionRisk | None = None,
    outside: bool = False,
) -> Iterator[ToolContext | None]:
    """Set the context for the duration of a tool run; always reset, even on error."""
    ctx = (
        ToolContext.from_scope(
            scope, confirmed=confirmed, approved_risk=approved_risk, outside=outside
        )
        if scope
        else None
    )
    token = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)


# Slice 10 D: what the owner presented with an approval (a passkey check made for that card). The
# approve route sets it around `Brain.approve`; the gateway's approval guard reads it on the card
# about to run. Request-scoped like everything above: another request never sees it.
_proof: contextvars.ContextVar[Any] = contextvars.ContextVar("jarvis_approval_proof", default=None)


def approval_proof() -> Any:
    return _proof.get()


@contextmanager
def presenting_proof(proof: Any) -> Iterator[None]:
    token = _proof.set(proof)
    try:
        yield
    finally:
        _proof.reset(token)


__all__ = [
    "ToolContext",
    "approval_proof",
    "current_tool_context",
    "presenting_proof",
    "require_tool_context",
    "tool_context",
]
