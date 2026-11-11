# tests/test_r11_c_phrases.py -- R11 Part C's No-AI phrases (plan D18): anchored patterns tried
# before every older router (`route_no_ai(..., extra=)`), ending in Part C's own tools. Every Part C
# tool is reachable by a phrase; "don't remind me to stand up" stops the nudge and sets no reminder;
# a one-off "remind me ... at 5 pm" and anything not about nudges are left to the other routers.
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from r11_fakes_c import part

from jarvis.helpers.nudges.phrases import PHRASES, route
from jarvis.offline.rules import NoAICall, route_no_ai

NOW = datetime(2026, 11, 10, 6, 30, tzinfo=UTC)

CASES: list[tuple[str, str, dict[str, str]]] = [
    ("don't remind me to stand up", "nudge_stop", {"kind": "standup"}),
    ("Do not remind me to drink water today.", "nudge_stop", {"kind": "water"}),
    ("stop water", "nudge_stop", {"kind": "water"}),
    ("stop stand-up nudges", "nudge_stop", {"kind": "standup"}),
    ("stop the focus reminders for good", "nudge_stop", {"kind": "focus", "for_good": "true"}),
    ("never remind me to stand up", "nudge_stop", {"kind": "standup"}),
    ("no more nudges today", "nudge_stop", {"kind": "all"}),
    ("Jarvis, stop all nudges", "nudge_stop", {"kind": "all"}),
    ("stop nudging me", "nudge_stop", {"kind": "all"}),
    ("snooze the water reminder for an hour", "nudge_snooze", {"kind": "water", "minutes": "60"}),
    ("snooze stand-up for 30 minutes", "nudge_snooze", {"kind": "standup", "minutes": "30"}),
    ("snooze water for half an hour", "nudge_snooze", {"kind": "water", "minutes": "30"}),
    ("snooze nudges for 2 hours", "nudge_snooze", {"kind": "all", "minutes": "120"}),
    (
        "snooze the activity nudge until tomorrow",
        "nudge_snooze",
        {"kind": "activity", "until": "tomorrow"},
    ),
    ("snooze", "nudge_snooze", {"kind": "all", "minutes": "60"}),
    ("resume water reminders", "nudge_resume", {"kind": "water"}),
    ("resume all nudges", "nudge_resume", {"kind": "all"}),
    ("turn on water reminders", "nudge_set", {"kind": "water", "on": "true"}),
    ("switch the stand-up nudge off", "nudge_set", {"kind": "standup", "on": "false"}),
    ("turn on the free time nudges", "nudge_set", {"kind": "free_time", "on": "true"}),
    ("turn on the focus nudge", "nudge_set", {"kind": "focus", "on": "true"}),
    ("turn on activity nudges", "nudge_set", {"kind": "activity", "on": "true"}),
    (
        "remind me to drink water every 45 minutes",
        "nudge_set",
        {"kind": "water", "on": "true", "every_minutes": "45"},
    ),
    (
        "remind me to stand up every hour",
        "nudge_set",
        {"kind": "standup", "on": "true", "every_minutes": "60"},
    ),
    ("remind me before my stand-up meeting", "nudge_set", {"kind": "standup", "meeting": "true"}),
    (
        "don't remind me about my standup meeting",
        "nudge_set",
        {"kind": "standup", "meeting": "false"},
    ),
    ("show my nudges", "nudge_status", {}),
    ("how much water have I had today?", "nudge_status", {}),
    ("I had a glass of water", "nudge_water_log", {"glasses": "1"}),
    ("drank 2 glasses of water", "nudge_water_log", {"glasses": "2"}),
    ("log water", "nudge_water_log", {"glasses": "1"}),
    ("I stood up", "nudge_standup_log", {}),
    ("stand-up done", "nudge_standup_log", {}),
    ("walk done", "nudge_activity_checkin", {"word": "walk", "outcome": "done"}),
    ("I did my yoga", "nudge_activity_checkin", {"word": "yoga", "outcome": "done"}),
    ("missed my walk", "nudge_activity_checkin", {"word": "walk", "outcome": "missed"}),
    ("I moved my gym", "nudge_activity_checkin", {"word": "gym", "outcome": "moved"}),
    ("what can I do with my free time?", "freetime_suggest", {}),
    ("I have 40 minutes free, what should I do?", "freetime_suggest", {"minutes": "40"}),
    ("suggest something to do", "freetime_suggest", {}),
    ("show my free-time list", "freetime_list", {}),
    (
        "add to my free-time list: read a novel, 45 minutes, indoor",
        "freetime_add",
        {"text": "read a novel", "minutes": "45", "place": "indoor"},
    ),
    ("add to my free time list: cycle by the lake", "freetime_add", {"text": "cycle by the lake"}),
    (
        "remove cycle by the lake from my free-time list",
        "freetime_remove",
        {"text": "cycle by the lake"},
    ),
    ("I did read a novel from my list", "freetime_done", {"text": "read a novel"}),
]


@pytest.mark.parametrize(("text", "tool", "args"), CASES)
def test_a_phrase_reaches_its_tool_with_no_model(
    text: str, tool: str, args: dict[str, str]
) -> None:
    got = route_no_ai(text, NOW, extra=PHRASES)
    assert got.calls == (NoAICall(tool, args),), (text, got)


def test_every_part_c_tool_is_reachable_by_a_phrase() -> None:
    tools = {t.name for t in part().part.tools}
    assert {tool for _, tool, _ in CASES} == tools


@pytest.mark.parametrize(
    "text",
    [
        "don't remind me to stand up",
        "do not remind me to stand up",
        "don't remind me to drink water",
    ],
)
def test_dont_remind_me_never_sets_a_reminder(text: str) -> None:
    calls = route_no_ai(text, NOW, extra=PHRASES).calls
    assert [c.tool for c in calls] == ["nudge_stop"]
    assert [c.tool for c in route_no_ai(text, NOW).calls] != ["nudge_stop"]  # without C: not this


@pytest.mark.parametrize(
    "text",
    [
        "remind me to drink water at 5 pm",
        "remind me to stand up in 10 minutes",
        "what's on my calendar today",
        "draft an email about water bills",
        "stop",
        "the water is cold",
        "x" * 300,
        "",
    ],
)
def test_anything_else_is_left_to_the_other_routers(text: str) -> None:
    assert route(text, NOW) is None
