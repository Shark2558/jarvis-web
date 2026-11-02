# src/jarvis/tools/taint.py
"""Has untrusted content reached the model in this request? (Layer 4, slice 8 D4)

The Brain computes it per tool round from the exact messages the model saw — any tool result
from a tool whose output is not marked `trusted_output` (mail, calendar, web, …; a result whose
call can't be found counts as untrusted) — and sets it around `Gateway.execute`. A tool may raise
its risk with it: `memory_save` becomes an approval card, so text other people wrote can never
become a stored "fact about the owner" without the owner seeing it.

Outside a Brain turn (an approval being executed, a script) the answer is "untrusted": the safe
default, which also makes an approved card consume its token.

Spoken turns (slice 9 review): the owner's message came through the microphone, so anyone in the
room (a TV, a guest, the keep-listening window) may have said it. The Brain marks such a turn
`spoken` as well as untrusted, and the gateway then turns EVERY write tool into an approval card
— not only the memory tools. Outside a turn the answer is "not spoken" (an approval being
executed was decided on screen).
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from jarvis.llm.base import ChatMessage, TextBlock, ToolCall, ToolResultBlock
from jarvis.tools.external import FENCE_PREFIX
from jarvis.tools.registry import ToolRegistry

_untrusted: contextvars.ContextVar[bool | None] = contextvars.ContextVar(
    "jarvis_untrusted_in_context", default=None
)
_spoken: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "jarvis_spoken_in_context", default=False
)


def untrusted_in_context() -> bool:
    flag = _untrusted.get()
    return True if flag is None else flag


def tainted_round() -> bool:
    """True only INSIDE a turn whose model has seen untrusted content (or a spoken turn).
    Unlike `untrusted_in_context`, outside a turn this is False: an approval being executed or
    a script is not a tainted round (slice 10 D review M2)."""
    return _untrusted.get() is True


def spoken_in_context() -> bool:
    """True while a tool call made on a spoken (`channel: voice`) turn is being decided."""
    return _spoken.get()


@contextmanager
def context_trust(*, untrusted: bool, spoken: bool = False) -> Iterator[None]:
    token = _untrusted.set(untrusted or spoken)
    spoken_token = _spoken.set(spoken)
    try:
        yield
    finally:
        _spoken.reset(spoken_token)
        _untrusted.reset(token)


def fenced_text_seen(messages: Sequence[ChatMessage]) -> bool:
    """True when a text block carries fenced external content: the note an attached document
    adds to the owner's turn (slice 10 E). An owner who types a fence only makes it stricter."""
    return any(
        isinstance(b, TextBlock) and FENCE_PREFIX in b.text
        for m in messages
        if not isinstance(m.content, str)
        for b in m.content
    )


def untrusted_seen(messages: Sequence[ChatMessage], registry: ToolRegistry) -> bool:
    """True when any tool result in `messages` came from a tool without trusted output, or an
    attached document's text is in them."""
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
    return fenced_text_seen(messages)


__all__ = [
    "context_trust",
    "fenced_text_seen",
    "spoken_in_context",
    "tainted_round",
    "untrusted_in_context",
    "untrusted_seen",
]
