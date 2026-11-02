# src/jarvis/tools/taint.py
"""Has untrusted content reached the model in this request? (Layer 4, slice 8 D4)

The Brain computes it per tool round from the exact messages the model saw (this turn's rounds
plus the rolling window of earlier turns) and sets it around `Gateway.execute`. A tool result is
untrusted unless one of these holds:
  - its tool's output is the owner's own data by nature (`Tool.trusted_output`: memory), or
  - slice 11 D8 — trust by provenance: the stored block is `trusted` (the gateway set it because
    the tool, declared `may_vouch`, found every item in that result written by the owner or by
    JARVIS for him: `jarvis.tools.provenance`), the result is not an error, and the call that
    produced it is a `may_vouch` tool. The flag is per result: one invite from someone else, one
    to-do from Gmail, makes that whole result untrusted.
Everything else — mail, web, a document, someone else's event or to-do, an error, a result whose
call can't be found, an attached file's fenced text — keeps the round tainted, and then every
write becomes a card (`policy.TAINTED_WRITES_ASK`) and memory_save asks. A trusted result never
clears taint other content brought: one untrusted result anywhere in the window is enough.
Item text is fenced as external content whether trusted or not.

What JARVIS writes from outside content stays outside (D8, security review of A+B). Approving
"add a to-do from this mail" lets the mail's words into the owner's own list, and the
owner-authored rule alone (creator self, no guests, no links) would trust them on the next read.
So a write whose content the round's outside text may have shaped — inside a turn
`content_tainted()` (content only: a spoken-only turn doesn't count, the owner said it), or an
approved card whose proposing round was content-tainted (`PendingAction.outside`, recorded when
the card is made; the owner saw the card, but not where its words came from) — runs with
`ToolContext.outside`, and the calendar, reminder and to-do tools mark what they write
(`provenance.mark_outside`, `tools.task_marks`). A marked item is never the owner's own, so a
later look-up of it taints the round again. Restores from Recently deleted keep the item's flag.

Outside a Brain turn (an approval being executed, a script) the answer is "untrusted": the safe
default, which also makes an approved card consume its token.

Spoken turns (slice 9 review): the owner's message came through the microphone, so anyone in the
room (a TV, a guest, the keep-listening window) may have said it. The Brain marks such a turn
`spoken` as well as untrusted, and the gateway then turns EVERY write tool into an approval card
— not only the memory tools. Outside a turn the answer is "not spoken" (an approval being
executed was decided on screen).

The owner's own words (slice 11 D7 a): the text of the owner's CURRENT message, set by the Brain
around each call of its tool rounds (`owner_text`; None outside a turn). A tool may ask first when
an argument did not come from them — a Gmail draft to an address the owner did not type in this
message becomes a card (`tools.gmail`).
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from jarvis.llm.base import ChatMessage, TextBlock, ToolCall, ToolResultBlock
from jarvis.tools.base import Tool
from jarvis.tools.external import FENCE_PREFIX
from jarvis.tools.registry import ToolRegistry

_untrusted: contextvars.ContextVar[bool | None] = contextvars.ContextVar(
    "jarvis_untrusted_in_context", default=None
)
_spoken: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "jarvis_spoken_in_context", default=False
)
_owner_text: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "jarvis_owner_text", default=None
)
_content: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "jarvis_content_tainted", default=False
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


def owner_text() -> str | None:
    """The owner's own words in the current message (None outside a turn)."""
    return _owner_text.get()


def content_tainted() -> bool:
    """True only INSIDE a turn whose model has seen other people's content — not merely a spoken
    turn. What a write made now contains may be their words (see the module docstring)."""
    return _content.get()


@contextmanager
def context_trust(
    *, untrusted: bool, spoken: bool = False, owner_text: str | None = None
) -> Iterator[None]:
    token = _untrusted.set(untrusted or spoken)
    spoken_token = _spoken.set(spoken)
    text_token = _owner_text.set(owner_text)
    content_token = _content.set(untrusted)
    try:
        yield
    finally:
        _content.reset(content_token)
        _owner_text.reset(text_token)
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


def result_trusted(block: ToolResultBlock, tool: Tool | None) -> bool:
    """One tool result: the owner's own by its tool's nature, or by its provenance (D8)."""
    if tool is None:
        return False
    if tool.trusted_output:
        return True
    return block.trusted and tool.may_vouch and not block.is_error


def untrusted_seen(messages: Sequence[ChatMessage], registry: ToolRegistry) -> bool:
    """True when any tool result in `messages` is not trusted (`result_trusted`), or an attached
    document's text is in them."""
    called: dict[str, str] = {}
    for m in messages:
        if isinstance(m.content, str):
            continue
        for b in m.content:
            if isinstance(b, ToolCall):
                called[b.id] = b.name
            elif isinstance(b, ToolResultBlock):
                if not result_trusted(b, registry.get(called.get(b.tool_use_id, ""))):
                    return True
    return fenced_text_seen(messages)


__all__ = [
    "content_tainted",
    "context_trust",
    "fenced_text_seen",
    "owner_text",
    "result_trusted",
    "spoken_in_context",
    "tainted_round",
    "untrusted_in_context",
    "untrusted_seen",
]
