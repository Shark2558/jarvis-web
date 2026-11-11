# tests/test_r11_a_phrases.py -- R11 Part A (D18): the No-AI phrases. Anchored and conservative:
# each one ends in Part A's own tool; anything else (a reminder, a nudge stop, a question that only
# mentions a bill) is left to the older patterns. Through `route_no_ai(extra=...)` they run first.
# "pay X" and "I paid X" are his only when X is one of his bills (code review M2): "pay rent" with
# no rent bill falls through to the older patterns.
from __future__ import annotations

import pytest
from r11_fakes import NOON_IST, UID
from r11_fakes_a import today_ctx

from jarvis.helpers.today import part as today_part
from jarvis.helpers.today.phrases import no_bills, phrases_for, today_phrases
from jarvis.offline.rules import NoAICall, NoAIRoute, route_no_ai

BILLS = ("Electricity", "Rent", "Water bill", "Gas", "Broadband")


def _knows(name: str) -> bool:
    key = " ".join(name.split()).casefold()
    return any(b.casefold() in (key, f"{key} bill") for b in BILLS)


def _route(text: str) -> NoAIRoute | None:
    return today_phrases(text, NOON_IST, _knows)


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
    route = _route(text)
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
    assert _route(text) is None


def test_they_run_before_the_older_patterns() -> None:
    phrases = phrases_for(_knows)
    route = route_no_ai("pay the electricity bill", NOON_IST, phrases)
    assert route.calls == (NoAICall("bill_pay_prepare", {"bill": "electricity"}),)
    reminder = route_no_ai("remind me to pay the electricity bill in 2 hours", NOON_IST, phrases)
    assert [c.tool for c in reminder.calls] == ["reminder_add"]


@pytest.mark.parametrize(
    "text",
    ["pay rent", "I paid for lunch", "I've paid the plumber", "mark lunch as paid", "pay Ravi"],
)
def test_pay_or_paid_with_no_bill_by_that_name_falls_through(text: str) -> None:
    assert today_phrases(text, NOON_IST, no_bills) is None
    route = route_no_ai(text, NOON_IST, phrases_for(no_bills))
    assert all(c.tool not in {"bill_pay_prepare", "bill_paid"} for c in route.calls)
    assert today_phrases("I paid for lunch", NOON_IST, _knows) is None  # no "for lunch" bill


async def test_the_parts_phrases_know_his_own_bills() -> None:
    c, _, _, _ = today_ctx()
    part = today_part.build(c)
    assert today_phrases("pay rent", NOON_IST, no_bills) is None
    (route,) = part.phrases
    assert route("pay the electricity bill", NOON_IST) is None  # no bill yet: not ours
    await part.services["bills"].add(UID, label="Electricity", amount="1240", day=13)
    got = route("pay the electricity bill", NOON_IST)
    assert got is not None and got.calls == (NoAICall("bill_pay_prepare", {"bill": "electricity"}),)
    assert route("pay rent", NOON_IST) is None
    assert route("what's my top priority?", NOON_IST) is not None  # the rest need no bill
