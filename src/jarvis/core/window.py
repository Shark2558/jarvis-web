# src/jarvis/core/window.py
"""Short-term memory: the rolling window of turns sent to the LLM (Layer 3).

Pure function so it is trivially testable. Budget is in characters (~4 chars/token) —
good enough for Phase 0; Phase 3 swaps in a real tokenizer count and summarisation of
evicted turns into long-term memory.

R11.1 D3: a reply that is one of JARVIS's own fixed lines for an answer with no words (or the
filler earlier releases stored: `core.fixed_lines.is_fixed`, a leaf) is never history. It is left
out here, for every brain, so no later turn can imitate it, and it uses none of the budget.
"""

from __future__ import annotations

from jarvis.core.fixed_lines import is_fixed
from jarvis.core.models import Turn
from jarvis.llm.base import ChatMessage, Role


def _filler(t: Turn) -> bool:
    return t.role is Role.ASSISTANT and not t.blocks and is_fixed(t.content)


def build_window(turns: list[Turn], *, max_turns: int, max_chars: int) -> list[ChatMessage]:
    """Return the most recent turns that fit both budgets, as a well-formed message list.

    Well-formed means: starts with a user turn, roles alternate, no empty content.
    """
    kept: list[Turn] = []
    used = 0
    for t in reversed(turns):
        if (not t.content.strip() and not t.blocks) or _filler(t):
            continue
        if len(kept) >= max_turns or used + len(t.content) > max_chars:
            break
        kept.append(t)
        used += len(t.content)
    kept.reverse()

    # must begin with the user; drop a dangling leading assistant turn
    while kept and kept[0].role is not Role.USER:
        kept.pop(0)

    # collapse accidental same-role runs (e.g. a failed assistant turn never recorded)
    msgs: list[ChatMessage] = []
    for t in kept:
        content: str | list = t.blocks if t.blocks else t.content
        if (
            msgs
            and msgs[-1].role == t.role
            and isinstance(content, str)
            and isinstance(msgs[-1].content, str)
        ):
            msgs[-1] = ChatMessage(role=t.role, content=msgs[-1].content + "\n\n" + content)
        else:
            msgs.append(ChatMessage(role=t.role, content=content))
    # a tool_result block must directly follow the assistant turn that requested it; drop a
    # leading orphan tool_result (window cut through a tool exchange)
    while (
        msgs
        and not isinstance(msgs[0].content, str)
        and any(getattr(b, "type", "") == "tool_result" for b in msgs[0].content)
    ):
        msgs.pop(0)
    while msgs and msgs[0].role is not Role.USER:
        msgs.pop(0)
    return msgs
