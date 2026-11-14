# src/jarvis/core/window.py
"""Short-term memory: the rolling window of turns sent to the LLM (Layer 3).

Pure function so it is trivially testable. Budget is in characters (~4 chars/token) —
good enough for Phase 0; Phase 3 swaps in a real tokenizer count and summarisation of
evicted turns into long-term memory.

R11.1 D3: a reply that is one of JARVIS's own fixed lines for an answer with no words (or the
filler earlier releases stored: `core.fixed_lines.is_fixed`, a leaf) is never history. It is left
out here, for every brain, so no later turn can imitate it, and it uses none of the budget.

R14 D9 ("Count tool results in the history", docs/plans/r14-hardening.md):
- every block counts toward the character cap (text, a tool call's name and arguments, a tool
  result), not only a turn's `content` (a tool-result turn has `content=""`);
- tool results older than the last `KEEP_FULL_ROUNDS` tool rounds are cut to `tool_result_chars`
  with `SHORTENED`, keeping their leading "untrusted tool output" line, `is_error` and `trusted`
  (send-side only: the stored rounds are never changed). The window is built once at the start of
  a turn, so a round of the current turn is never cut, and the cut is the same every time;
- old turns are dropped in chunks: when the window would pass a cap, its start moves forward
  until it holds `DROP_TO` (70 %) of it, so the start stays put for several replies and the
  provider's cache keeps its prefix.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Final

from jarvis.core.fixed_lines import is_fixed
from jarvis.core.models import Turn
from jarvis.llm.base import (
    ChatMessage,
    ContentBlock,
    MessageBlock,
    Role,
    TextBlock,
    ToolCall,
    ToolResultBlock,
)

KEEP_FULL_ROUNDS: Final = 2  # the most recent tool rounds whose results are sent whole
DEFAULT_TOOL_RESULT_CHARS: Final = 2_000  # = Settings.history_tool_result_chars' default
SHORTENED: Final = "… [shortened]"
DROP_TO: Final = 0.7  # a window over a cap drops old turns down to this share of it
_HEADER_START = "[untrusted tool output"

Content = str | list[ContentBlock]


def _filler(t: Turn) -> bool:
    return t.role is Role.ASSISTANT and not t.blocks and is_fixed(t.content)


def block_chars(b: MessageBlock) -> int:
    if isinstance(b, TextBlock):
        return len(b.text)
    if isinstance(b, ToolCall):
        return len(b.name) + len(json.dumps(b.arguments, ensure_ascii=False))
    if isinstance(b, ToolResultBlock):
        return len(b.content)
    return 0  # a picture: added after the window, never part of its budget


def message_chars(m: ChatMessage) -> int:
    """The characters one message sends: its text, or every block it carries."""
    if isinstance(m.content, str):
        return len(m.content)
    return sum(block_chars(b) for b in m.content)


def _content_chars(content: Content) -> int:
    return len(content) if isinstance(content, str) else sum(block_chars(b) for b in content)


def shorten(block: ToolResultBlock, limit: int) -> ToolResultBlock:
    """The same result cut to `limit` characters of its body (its header line kept)."""
    head, body = "", block.content
    if body.startswith(_HEADER_START) and "\n" in body:
        cut = body.index("\n") + 1
        head, body = body[:cut], body[cut:]
    if len(body) <= limit:
        return block
    return block.model_copy(update={"content": head + body[:limit] + SHORTENED})


def _is_result_turn(t: Turn) -> bool:
    return any(isinstance(b, ToolResultBlock) for b in t.blocks)


def _contents(turns: Sequence[Turn], tool_result_chars: int) -> list[Content]:
    """Each turn as it is sent: results older than the last rounds cut (new block objects)."""
    rounds = [i for i, t in enumerate(turns) if _is_result_turn(t)]
    old = set(rounds[:-KEEP_FULL_ROUNDS]) if len(rounds) > KEEP_FULL_ROUNDS else set()
    out: list[Content] = []
    for i, t in enumerate(turns):
        if not t.blocks:
            out.append(t.content)
        elif i in old:
            out.append(
                [
                    shorten(b, tool_result_chars) if isinstance(b, ToolResultBlock) else b
                    for b in t.blocks
                ]
            )
        else:
            out.append(list(t.blocks))
    return out


def window_start(sizes: Sequence[int], *, max_turns: int, max_chars: int) -> int:
    """Where the window starts, replayed over the history as it grew: it stays put while the
    turns from it fit both caps, and jumps forward to `DROP_TO` of them when they don't. The
    newest turn is always kept."""
    turns_to, chars_to = int(max_turns * DROP_TO), int(max_chars * DROP_TO)
    start, used = 0, 0
    for n, size in enumerate(sizes, start=1):
        used += size
        if n - start <= max_turns and used <= max_chars:
            continue
        while start < n - 1 and (n - start > turns_to or used > chars_to):
            used -= sizes[start]
            start += 1
    return start


def build_window(
    turns: list[Turn],
    *,
    max_turns: int,
    max_chars: int,
    tool_result_chars: int = DEFAULT_TOOL_RESULT_CHARS,
) -> list[ChatMessage]:
    """Return the most recent turns that fit both budgets, as a well-formed message list.

    Well-formed means: starts with a user turn, roles alternate, no empty content, and every
    tool result directly follows the call that asked for it.
    """
    eligible = [t for t in turns if (t.content.strip() or t.blocks) and not _filler(t)]
    contents = _contents(eligible, tool_result_chars)
    sizes = [_content_chars(c) for c in contents]
    start = window_start(sizes, max_turns=max_turns, max_chars=max_chars)
    return _well_formed(eligible[start:], contents[start:])


def _well_formed(turns: Sequence[Turn], contents: Sequence[Content]) -> list[ChatMessage]:
    kept = list(zip(turns, contents, strict=True))
    # must begin with the user; drop a dangling leading assistant turn
    while kept and kept[0][0].role is not Role.USER:
        kept.pop(0)
    # collapse accidental same-role runs (e.g. a failed assistant turn never recorded)
    msgs: list[ChatMessage] = []
    for t, content in kept:
        last = msgs[-1] if msgs else None
        if (
            last is not None
            and last.role == t.role
            and isinstance(content, str)
            and isinstance(last.content, str)
        ):
            msgs[-1] = ChatMessage(role=t.role, content=last.content + "\n\n" + content)
        else:
            body: str | list[MessageBlock] = content if isinstance(content, str) else [*content]
            msgs.append(ChatMessage(role=t.role, content=body))
    # a tool_result block must directly follow the assistant turn that requested it; drop a
    # leading orphan tool_result (window cut through a tool exchange)
    while (
        msgs
        and not isinstance(msgs[0].content, str)
        and any(isinstance(b, ToolResultBlock) for b in msgs[0].content)
    ):
        msgs.pop(0)
    while msgs and msgs[0].role is not Role.USER:
        msgs.pop(0)
    return msgs


__all__ = [
    "DEFAULT_TOOL_RESULT_CHARS",
    "DROP_TO",
    "KEEP_FULL_ROUNDS",
    "SHORTENED",
    "block_chars",
    "build_window",
    "message_chars",
    "shorten",
    "window_start",
]
