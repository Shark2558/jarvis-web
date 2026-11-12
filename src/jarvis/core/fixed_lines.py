# src/jarvis/core/fixed_lines.py
"""JARVIS's own fixed lines for an answer with no words (R11.1; docs/plans/r11-1-observations.md
D2.3, D3; Layer 4). A leaf: it imports nothing of JARVIS, so `core.window` (a pure helper) and
`core.finish` can both use it without pulling in the gateway, billing or the web ledger.

- `no_words`: the one line chosen by CODE from what happened (approvals waiting, steps that ran,
  steps that failed, cut off), never from the model; "" when nothing happened.
- `is_fixed`: those lines, and the filler R11 and earlier stored (`OLD_FILLER`), are known by
  their words, so they are stored marked and left out of every model's window.
"""

from __future__ import annotations

import re

# What R11 and earlier said (and stored) for an answer with no words. Only ever matched now.
OLD_FILLER = "I have nothing to add, Sir."
CUT_TAIL = "Ask me for a smaller piece, or raise the answer length in Settings."
CUT_OFF = f"My answer was cut off before I could finish, Sir. {CUT_TAIL}"
CUT_ALSO = "My answer was cut off before I could finish."  # after another sentence's "Sir"
EMPTY = (
    "The AI returned an empty answer, Sir. Please ask again; if it repeats, switch brain in the "
    "top bar."
)
ACTIVITY = "Activity shows what ran."
_CARDS = r"I've prepared \d+ approvals? for you, Sir\."
_WORDS = rf"the AI gave me no words to report (?:it|them)\. {re.escape(ACTIVITY)}"
_STEPS = rf"(?:I did \d+ steps?(?: and \d+ failed,)? but|\d+ steps? failed and) {_WORDS}"
_CUT = rf"My answer was cut off before I could finish(?:, Sir)?\. {re.escape(CUT_TAIL)}"
_FIXED = re.compile(rf"(?:{_CARDS})?(?: ?{_STEPS})?(?: ?{_CUT})?")


def _count(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _steps(steps: int, failed: int) -> str:
    """The steps that ran and the ones that failed (raised, or their arguments were refused)."""
    them = "it" if steps + failed == 1 else "them"
    words = f"the AI gave me no words to report {them}. {ACTIVITY}"
    if steps > 0 and failed > 0:
        return f"I did {_count(steps, 'step')} and {failed} failed, but {words}"
    if steps > 0:
        return f"I did {_count(steps, 'step')} but {words}"
    return f"{_count(failed, 'step')} failed and {words}"


def no_words(*, cards: int = 0, steps: int = 0, failed: int = 0, cut: bool = False) -> str:
    """The fixed line for an answer with no words, from what happened ("" when nothing did and
    it was not cut off: the caller says `EMPTY`)."""
    parts: list[str] = []
    if cards > 0:
        parts.append(f"I've prepared {_count(cards, 'approval')} for you, Sir.")
    if steps > 0 or failed > 0:
        parts.append(_steps(max(steps, 0), max(failed, 0)))
    if cut:
        parts.append(f"{CUT_ALSO} {CUT_TAIL}" if parts else CUT_OFF)
    return " ".join(parts)


def is_fixed(text: str) -> bool:
    """`text` is one of JARVIS's own fixed lines for an answer with no words (or the old filler):
    never history for a model (`core.window`), stored marked tool-derived."""
    t = text.strip()
    return bool(t) and (t in (EMPTY, OLD_FILLER) or _FIXED.fullmatch(t) is not None)


__all__ = [
    "ACTIVITY",
    "CUT_ALSO",
    "CUT_OFF",
    "CUT_TAIL",
    "EMPTY",
    "OLD_FILLER",
    "is_fixed",
    "no_words",
]
