# tests/test_no_ai_rules.py
"""No-AI mode, pass 1 (R4 D7): deterministic intent routing, no model anywhere."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from jarvis.offline.rules import NO_AI_LINE, route_no_ai

NOW = datetime(2026, 11, 5, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


def calls(text: str) -> list[tuple[str, dict]]:
    route = route_no_ai(text, NOW)
    return [(c.tool, c.arguments) for c in route.calls]


@pytest.mark.parametrize(
    "text", ["run a systems check", "Jarvis, system check please", "systems check", "health check"]
)
def test_systems_check_routes_to_the_tool(text: str) -> None:
    assert calls(text) == [("systems_check", {})]


@pytest.mark.parametrize("text", ["show my vitals", "how are my api keys and quotas", "vitals"])
def test_vitals_routes_to_the_tool(text: str) -> None:
    assert calls(text) == [("vitals_show", {})]


def test_calendar_today_is_the_owners_day() -> None:
    ((tool, args),) = calls("what's on my calendar today")

    assert tool == "calendar_list_events"
    assert args["start"].startswith("2026-11-05T00:00:00")
    assert args["end"].startswith("2026-11-06T00:00:00")


def test_calendar_tomorrow_and_week() -> None:
    ((_, tomorrow),) = calls("what meetings do I have tomorrow")
    ((_, week),) = calls("show my schedule this week")

    assert tomorrow["start"].startswith("2026-11-06T00:00:00")
    assert week["end"].startswith("2026-11-12T00:00:00")


def test_calendar_with_no_day_defaults_to_today() -> None:
    ((_, args),) = calls("show my calendar")

    assert args["start"].startswith("2026-11-05T00:00:00")


def test_reminders_list() -> None:
    assert calls("what are my reminders") == [("reminders_list", {})]


def test_timer_in_minutes_becomes_a_reminder_at_the_right_time() -> None:
    ((tool, args),) = calls("set a timer for 10 minutes")

    assert tool == "reminder_add"
    assert args["when"].startswith("2026-11-05T10:10:00")
    assert args["text"] == "Timer"


def test_timer_in_hours_and_seconds_round_up_to_a_minute() -> None:
    ((_, hours),) = calls("start a timer for 2 hours")
    ((_, secs),) = calls("set a timer for 30 seconds")

    assert hours["when"].startswith("2026-11-05T12:00:00")
    assert secs["when"].startswith("2026-11-05T10:01:00")


def test_remind_me_in_minutes() -> None:
    ((tool, args),) = calls("remind me to call Rahul in 30 minutes")

    assert tool == "reminder_add"
    assert args["text"] == "call Rahul"
    assert args["when"].startswith("2026-11-05T10:30:00")


def test_remind_me_at_a_clock_time_today_or_tomorrow_if_past() -> None:
    ((_, later),) = calls("remind me to take the parcel at 5:30 pm")
    ((_, past),) = calls("remind me to stretch at 8 am")

    assert later["when"].startswith("2026-11-05T17:30:00")
    assert past["when"].startswith("2026-11-06T08:00:00")


def test_remind_me_without_a_time_asks_for_one_and_calls_nothing() -> None:
    route = route_no_ai("remind me to call Rahul", NOW)

    assert route.calls == () and "when" in route.reply.lower()


def test_take_a_note_saves_the_owners_words() -> None:
    assert calls("take a note: buy filter coffee") == [
        ("kb_add_note", {"text": "buy filter coffee"})
    ]


def test_search_notes() -> None:
    assert calls("search my notes for plumber") == [("kb_search", {"query": "plumber"})]


def test_tasks() -> None:
    assert calls("show my to-do list") == [("tasks_list", {})]


def test_research_person_then_open_profiles() -> None:
    assert calls("open profiles for Satya Nadella") == [
        ("research_person", {"name": "Satya Nadella"}),
        ("people_open_profiles", {}),
    ]


def test_research_with_context() -> None:
    assert calls("research Satya Nadella at Microsoft") == [
        ("research_person", {"name": "Satya Nadella", "context": "Microsoft"}),
        ("people_open_profiles", {}),
    ]


def test_open_profiles_alone_opens_the_last_research() -> None:
    assert calls("open the profiles") == [("people_open_profiles", {})]


@pytest.mark.parametrize(
    "text",
    [
        "draft an email to the vendor",
        "write me a poem",
        "summarise this article",
        "explain quantum computing",
        "teach me Spanish",
        "translate hello into Malayalam",
        "what is the meaning of life",
        "",
    ],
)
def test_generative_or_unknown_requests_get_the_fixed_line(text: str) -> None:
    route = route_no_ai(text, NOW)

    assert route.calls == ()
    assert route.reply == NO_AI_LINE == "That needs the AI switched on, Sir."


def test_a_private_person_request_still_reaches_the_tool_so_the_guard_decides() -> None:
    # the router never second-guesses scope: research_person's own argument check refuses
    assert calls("research Ravi Kumar my neighbour home address")[0][0] == "research_person"


def test_text_inside_a_note_is_not_re_routed() -> None:
    assert calls("take a note: run a systems check")[0][0] == "kb_add_note"
