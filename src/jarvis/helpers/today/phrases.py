# src/jarvis/helpers/today/phrases.py
"""Part A's No-AI phrases (docs/plans/r11-free-helpers.md D18): fixed, anchored patterns tried
before every older one, each ending in Part A's own tools through the gateway (policy, cards and
R3 tokens all apply: "pay the electricity bill" makes the same R3 card with the AI off).

Conservative on purpose: the whole message must be the phrase (an optional "Jarvis," and "please",
end punctuation), so "remind me to pay the electricity bill tomorrow" is never taken here (it is a
reminder) and nothing about nudges ("don't remind me to stand up") is either (Part C's).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime

from jarvis.offline.rules import NoAICall, NoAIRoute

_I = re.IGNORECASE
_LEAD = r"^(?:(?:hey|ok|okay)\s+)?(?:jarvis[,\s]+)?(?:please\s+)?"
_END = r"(?:\s+please)?[\s.!?]*$"
_NAME = r"(?:the\s+|my\s+)?(?P<bill>[A-Za-z][A-Za-z0-9 &'.-]{0,39}?)"
_BILL = r"(?:\s+bill)?"


def _p(body: str) -> re.Pattern[str]:
    return re.compile(_LEAD + body + _END, _I)


FOCUS = _p(
    r"(?:what(?:'s|\s+is)\s+)?(?:my\s+)?top\s+priority(?:\s+(?:now|right\s+now|today))?"
    r"|what\s+should\s+i\s+(?:do|focus\s+on)\s+(?:first|now|next)"
)
PENDING = _p(
    r"what(?:'s|\s+is)\s+pending(?:\s+today)?"
    r"|(?:show|list)\s+(?:me\s+)?(?:what(?:'s|\s+is)\s+)?pending(?:\s+(?:items|things))?"
    r"|pending\s+(?:items|things|list)"
)
BILLS = _p(
    r"(?:(?:show|list)\s+(?:me\s+)?)?(?:my\s+)?bills(?:\s+due)?"
    r"|what\s+bills\s+are\s+due(?:\s+(?:today|this\s+week))?"
)
PAID = (
    _p(r"i(?:'ve|\s+have)?\s+paid\s+" + _NAME + _BILL),
    _p(r"mark\s+" + _NAME + _BILL + r"\s+(?:as\s+)?paid"),
)
PAY = (
    _p(r"pay\s+" + _NAME + _BILL),
    _p(r"get\s+" + _NAME + _BILL + r"\s+payment\s+ready"),
    _p(r"prepare\s+" + _NAME + _BILL + r"\s+payment"),
)
BIRTHDAYS = _p(
    r"whose\s+birthday\s+is\s+(?:it\s+)?today"
    r"|(?:any\s+)?birthdays\s+(?:today|this\s+week|coming\s+up)"
    r"|who(?:'s|\s+has|\s+is)\s+(?:having\s+)?(?:a\s+)?birthday\s+today"
    r"|(?:upcoming|next)\s+birthdays"
)


def _call(tool: str, **args: str) -> NoAIRoute:
    return NoAIRoute((NoAICall(tool, dict(args)),))


def _named(patterns: tuple[re.Pattern[str], ...], text: str) -> str | None:
    for pattern in patterns:
        if (m := pattern.match(text)) is not None:
            return m["bill"].strip()
    return None


def today_phrases(text: str, now: datetime) -> NoAIRoute | None:
    """The tool calls for one of Part A's phrases, or None (not ours)."""
    t = " ".join(text.split())
    if FOCUS.match(t):
        return _call("focus_now")
    if PENDING.match(t):
        return _call("pending_list")
    if BIRTHDAYS.match(t):
        return _call("contacts_birthdays")
    if BILLS.match(t):
        return _call("bill_list")
    if (bill := _named(PAID, t)) is not None:
        return _call("bill_paid", bill=bill)
    if (bill := _named(PAY, t)) is not None:
        return _call("bill_pay_prepare", bill=bill)
    return None


PHRASES: tuple[Callable[[str, datetime], NoAIRoute | None], ...] = (today_phrases,)

__all__ = ["PHRASES", "today_phrases"]
