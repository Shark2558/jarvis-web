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


@dataclass(frozen=True)
class ToolContext:
    user_id: str
    session_id: str | None
    scope: str

    @classmethod
    def from_scope(cls, scope: str) -> ToolContext:
        user_id, _, session_id = scope.partition(":")
        return cls(user_id=user_id, session_id=session_id or None, scope=scope)


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
def tool_context(scope: str | None) -> Iterator[ToolContext | None]:
    """Set the context for the duration of a tool run; always reset, even on error."""
    ctx = ToolContext.from_scope(scope) if scope else None
    token = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)


__all__ = ["ToolContext", "current_tool_context", "require_tool_context", "tool_context"]
