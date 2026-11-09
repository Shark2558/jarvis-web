# tests/test_no_ai_conservative.py
"""The no-AI router is CONSERVATIVE (R4 D-D4): with no model to arbitrate, it under-matches and
says "That needs the AI switched on" rather than guess, never fires a timer early, and never
turns an odd number into a 500."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from jarvis.offline.rules import NEEDS_TIME_LINE, NO_AI_LINE, route_no_ai

IST = ZoneInfo("Asia/Kolkata")


def at(text: str, hour: int = 10, minute: int = 0, second: int = 0):
    return route_no_ai(text, datetime(2026, 11, 5, hour, minute, second, tzinfo=IST))


def calls(text: str) -> list[tuple[str, dict]]:
    return [(c.tool, c.arguments) for c in at(text).calls]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("set a timer for 30 seconds", "10:02:00"),
        ("set a timer for 59 seconds", "10:02:00"),
        ("set a timer for 61 seconds", "10:02:00"),
        ("set a timer for 15 seconds", "10:01:00"),
    ],
)
def test_timer_never_fires_early_when_the_clock_has_seconds(text: str, expected: str) -> None:
    route = at(text, 10, 0, 45)

    assert route.calls[0].arguments["when"][11:19] == expected


def test_a_24_hour_timer_lands_on_the_next_day_rounded_up() -> None:
    route = at("set a timer for 24 hours", 10, 0, 45)

    assert route.calls[0].arguments["when"].startswith("2026-11-06T10:01:00")


def test_an_exact_minute_is_not_bumped() -> None:
    route = at("set a timer for 2 hours", 10, 0, 0)

    assert route.calls[0].arguments["when"].startswith("2026-11-05T12:00:00")


@pytest.mark.parametrize(
    "text",
    [
        "set a timer for 0 seconds",
        "set a timer for 0 minutes",
        "set a timer for 99999999999999999999 hours",
        "set a timer for 10001 minutes",
        "set a timer for 2 hours 30 minutes",
        "set a timer for 1 hour and 15 minutes",
        "remind me to call Rahul in 0 minutes",
        "remind me to call Rahul in 99999999999999999999 hours",
        "remind me to call Rahul at 5",
        "remind me to call Rahul at 17",
    ],
)
def test_odd_amounts_and_ambiguous_times_ask_for_a_time_not_a_guess(text: str) -> None:
    route = at(text)

    assert route.calls == () and route.reply == NEEDS_TIME_LINE


def test_a_24_hour_clock_time_with_minutes_is_understood() -> None:
    ((_, args),) = calls("remind me to stretch at 17:30")

    assert args["when"].startswith("2026-11-05T17:30:00")


def test_a_leading_to_is_stripped_from_the_reminder_text() -> None:
    ((_, args),) = calls("remind me to to call Rahul in 5 minutes")

    assert args["text"] == "call Rahul"


@pytest.mark.parametrize(
    "text",
    [
        "look up the weather",
        "research how to bake bread",
        "look up the meaning of serendipity",
        "find out about the cricket score",
        "my tasks are boring, tell me a joke",
        "the schedule of the train to Delhi",
        "what is the quota system in universities",
        "can you explain the meetings culture at Amazon",
    ],
)
def test_ordinary_requests_are_not_mistaken_for_commands(text: str) -> None:
    route = at(text)

    assert route.calls == () and route.reply == NO_AI_LINE


@pytest.mark.parametrize(
    ("text", "tool"),
    [
        ("show my schedule", "calendar_list_events"),
        ("what's my schedule today", "calendar_list_events"),
        ("tasks", "tasks_list"),
        ("show my tasks", "tasks_list"),
        ("what is my quota", "vitals_show"),
        ("quota", "vitals_show"),
    ],
)
def test_anchored_command_forms_still_route(text: str, tool: str) -> None:
    assert calls(text)[0][0] == tool


@pytest.mark.parametrize(
    "text", ["research priya nair", "research Priya", "research the vendor", "look up weather"]
)
def test_research_needs_a_proper_name(text: str) -> None:
    assert at(text).calls == ()


def test_research_is_anchored_at_the_start_of_the_command() -> None:
    assert at("can you please look up Satya Nadella for me").calls == ()


def test_profiles_of_a_name_routes() -> None:
    assert calls("profiles of Satya Nadella")[0] == ("research_person", {"name": "Satya Nadella"})


def test_a_trailing_private_ask_still_reaches_the_tool_so_its_filters_decide() -> None:
    first = calls("research Ravi Kumar my neighbour home address")[0]

    assert first[0] == "research_person" and first[1]["name"] == "Ravi Kumar"
