# tests/test_r11_a_phrases.py -- R11 Part A (D18): the No-AI phrases. Anchored and conservative:
# each one ends in Part A's own tool; anything else (a reminder, a nudge stop, a question that only
# mentions a bill) is left to the older patterns. Through `route_no_ai(extra=...)` they run first.
from __future__ import annotations

import pytest
from r11_fakes import NOON_IST

from jarvis.helpers.today.phrases import PHRASES, today_phrases
from jarvis.offline.rules import NoAICall, route_no_ai


@pytest.mark.parametrize(
    ("text", "tool", "args"),
    [
        ("What's my top priority?", "focus_now", {}),
        ("Jarvis, top priority now", "focus_now", {}),
        ("what should I do first", "focus_now", {}),
        ("What is pending?", "pending_list", {}),
        ("show me pending items", "pending_list", {}),
        ("show my bills", "bill_list", {}),
        ("what bills are due this week", "bill_list", {}),
        ("I paid the electricity bill", "bill_paid", {"bill": "electricity"}),
        ("I've paid my Rent.", "bill_paid", {"bill": "Rent"}),
        ("mark water bill as paid", "bill_paid", {"bill": "water"}),
        ("pay the electricity bill", "bill_pay_prepare", {"bill": "electricity"}),
        ("please get the Gas payment ready", "bill_pay_prepare", {"bill": "Gas"}),
        ("prepare the broadband bill payment", "bill_pay_prepare", {"bill": "broadband"}),
        ("whose birthday is today?", "contacts_birthdays", {}),
        ("any birthdays this week", "contacts_birthdays", {}),
    ],
)
def test_each_phrase_ends_in_part_as_tool(text: str, tool: str, args: dict[str, str]) -> None:
    route = today_phrases(text, NOON_IST)
    assert route is not None and route.calls == (NoAICall(tool, args),)


@pytest.mark.parametrize(
    "text",
    [
        "remind me to pay the electricity bill tomorrow",
        "don't remind me to stand up",
        "stop stand-up nudges",
        "how much was the electricity bill last month?",
        "pay attention to the meeting and tell me what's pending in it",
        "send the bill to Ravi",
        "pay",
    ],
)
def test_anything_else_is_not_ours(text: str) -> None:
    assert today_phrases(text, NOON_IST) is None


def test_they_run_before_the_older_patterns() -> None:
    route = route_no_ai("pay the electricity bill", NOON_IST, PHRASES)
    assert route.calls == (NoAICall("bill_pay_prepare", {"bill": "electricity"}),)
    reminder = route_no_ai("remind me to pay the electricity bill in 2 hours", NOON_IST, PHRASES)
    assert [c.tool for c in reminder.calls] == ["reminder_add"]
