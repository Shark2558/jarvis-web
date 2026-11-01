# src/jarvis/tools/taint.py
"""Has untrusted content reached the model in this request? (Layer 4, slice 8 D4)

The Brain computes it per tool round from the exact messages the model saw — any tool result
from a tool whose output is not marked `trusted_output` (mail, calendar, web, …; a result whose
call can't be found counts as untrusted) — and sets it around `Gateway.execute`. A tool may raise
its risk with it: `memory_save` becomes an approval card, so text other people wrote can never
become a stored "fact about the owner" without the owner seeing it.

Outside a Brain turn (an approval being executed, a script) the answer is "untrusted": the safe
default, which also makes an approved card consume its token.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from jarvis.llm.base import ChatMessage, ToolCall, ToolResultBlock
from jarvis.tools.registry import ToolRegistry

_untrusted: contextvars.ContextVar[bool | None] = contextvars.ContextVar(
    "jarvis_untrusted_in_context", default=None
)


def untrusted_in_context() -> bool:
    flag = _untrusted.get()
    return True if flag is None else flag


@contextmanager
def context_trust(*, untrusted: bool) -> Iterator[None]:
    token = _untrusted.set(untrusted)
    try:
        yield
    finally:
        _untrusted.reset(token)


def untrusted_seen(messages: Sequence[ChatMessage], registry: ToolRegistry) -> bool:
    """True when any tool result in `messages` came from a tool without trusted output."""
    called: dict[str, str] = {}
    for m in messages:
        if isinstance(m.content, str):
            continue
        for b in m.content:
            if isinstance(b, ToolCall):
                called[b.id] = b.name
            elif isinstance(b, ToolResultBlock):
                tool = registry.get(called.get(b.tool_use_id, ""))
                if tool is None or not tool.trusted_output:
                    return True
    return False


__all__ = ["context_trust", "untrusted_in_context", "untrusted_seen"]
