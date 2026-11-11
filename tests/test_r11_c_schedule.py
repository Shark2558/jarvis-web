# tests/test_r11_c_schedule.py -- R11 Part C: the nudge settings and their schedule (plan items
# 8, 9, 11, 12; owner decision 9: stand-up every 60 min, water every 90 min, 09:30-18:30, Monday to
# Saturday, each OFF until he switches it on). Pure code, no I/O.
from __future__ import annotations

from datetime import date, timedelta

import pytest
from pydantic import ValidationError
from r11_fakes_c import IST, at_ist

from jarvis.helpers.nudges import models, schedule
from jarvis.helpers.nudges.models import DEFAULTS, Idea, Nudge, NudgeSettings, kind_of

MONDAY = date(2026, 11, 9)
SUNDAY = date(2026, 11, 15)


def test_the_owner_defaults_are_every_nudge_off_with_his_windows() -> None:
    s = NudgeSettings()
    assert all(not s.nudge(k).on for k in models.NUDGE_KINDS)
    up, water = s.nudge("nudge_standup"), s.nudge("nudge_hydrate")
    assert (up.every, up.start, up.end, up.days) == (60, "09:30", "18:30", (0, 1, 2, 3, 4, 5))
    assert (water.every, water.start, water.end) == (90, "09:30", "18:30")
    assert up.meeting is False and up.word == "stand-up"  # the meeting variant: built, off
    assert s.nudge("nudge_focus").times and s.nudge("nudge_free_time").times
    assert "walk" in s.nudge("nudge_activity").words


@pytest.mark.parametrize(
    ("said", "kind"),
    [
        ("standup", "nudge_standup"),
        ("Stand-up", "nudge_standup"),
        ("stand up", "nudge_standup"),
        ("water", "nudge_hydrate"),
        ("hydration", "nudge_hydrate"),
        ("drinking water", "nudge_hydrate"),
        ("activity", "nudge_activity"),
        ("free time", "nudge_free_time"),
        ("free-time", "nudge_free_time"),
        ("focus", "nudge_focus"),
        ("top priority", "nudge_focus"),
        ("all", "*"),
        ("nudges", "*"),
    ],
)
def test_the_kinds_he_may_name(said: str, kind: str) -> None:
    assert kind_of(said) == kind


def test_an_unknown_kind_is_refused_in_plain_words() -> None:
    with pytest.raises(ValueError, match="stand-up, water"):
        kind_of("coffee")


@pytest.mark.parametrize(
    "bad",
    [
        {"start": "9:30"},
        {"start": "18:30", "end": "09:30"},
        {"every": 5},
        {"every": 600},
        {"days": ()},
        {"days": (7,)},
        {"times": ("25:00",)},
        {"times": tuple(f"1{i}:00" for i in range(8))},
        {"word": "x"},
        {"word": "stand-up<script>"},
        {"words": ("walk", "")},
        {"words": tuple(f"w{i}x" for i in range(11))},
        {"colour": "red"},
    ],
)
def test_a_nudge_refuses_settings_outside_its_limits(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Nudge.model_validate({**DEFAULTS["nudge_standup"].model_dump(), **bad})


def test_an_idea_is_his_own_short_text_with_minutes_and_a_place() -> None:
    idea = Idea.new("  Read a  novel ", 45, "indoor")
    got = (idea.text, idea.minutes, idea.place, idea.last_done)
    assert got == ("Read a novel", 45, "indoor", None)
    assert len(idea.id) == 8
    for text, minutes, place in (("", 30, "indoor"), ("x" * 81, 30, "any"), ("Run", 2, "any")):
        with pytest.raises(ValueError):
            Idea.new(text, minutes, place)
    with pytest.raises(ValueError):
        Idea.new("Swim", 30, "roof")  # type: ignore[arg-type]


def test_the_free_time_list_holds_at_most_fifty_ideas() -> None:
    ideas = tuple(Idea.new(f"Idea {i}", 30, "any") for i in range(models.MAX_IDEAS))
    s = NudgeSettings(ideas=ideas)
    with pytest.raises(ValueError, match="50"):
        s.with_idea(Idea.new("One more", 30, "any"))


def test_changing_a_nudge_returns_new_settings_and_keeps_the_old() -> None:
    s = NudgeSettings()
    t = s.changed("nudge_hydrate", {"on": True, "every": 45})
    assert t.nudge("nudge_hydrate").every == 45 and t.nudge("nudge_hydrate").on
    assert s.nudge("nudge_hydrate").every == 90 and not s.nudge("nudge_hydrate").on
    with pytest.raises(ValueError):
        s.changed("nudge_hydrate", {"every": "often"})


# ---- the schedule --------------------------------------------------------------------------------
def test_stand_up_slots_are_each_hour_after_sitting_down_inside_the_window() -> None:
    up = DEFAULTS["nudge_standup"]
    got = schedule.slots("nudge_standup", up, MONDAY, IST)
    want = [at_ist(MONDAY, f"{h}:30") for h in range(10, 18)]
    assert got == want  # 10:30 ... 17:30: eight, inside the default cap of 8; never 18:30


def test_water_slots_are_every_ninety_minutes() -> None:
    got = schedule.slots("nudge_hydrate", DEFAULTS["nudge_hydrate"], MONDAY, IST)
    assert got == [at_ist(MONDAY, t) for t in ("11:00", "12:30", "14:00", "15:30", "17:00")]


def test_sunday_has_no_slots_by_default_and_times_kinds_use_his_times() -> None:
    assert schedule.slots("nudge_standup", DEFAULTS["nudge_standup"], SUNDAY, IST) == []
    focus = DEFAULTS["nudge_focus"]
    assert schedule.slots("nudge_focus", focus, MONDAY, IST) == [
        at_ist(MONDAY, t) for t in focus.times
    ]


def test_the_due_slot_is_the_latest_one_reached_and_never_a_stale_one() -> None:
    slots = schedule.slots("nudge_hydrate", DEFAULTS["nudge_hydrate"], MONDAY, IST)
    eleven = at_ist(MONDAY, "11:00")
    assert schedule.due(slots, eleven - timedelta(seconds=1)) is None  # never early
    assert schedule.due(slots, eleven) == eleven
    assert schedule.due(slots, eleven + timedelta(minutes=29)) == eleven
    assert schedule.due(slots, eleven + timedelta(minutes=31)) is None  # stale: skipped
    assert schedule.due(slots, at_ist(MONDAY, "12:34")) == at_ist(MONDAY, "12:30")


def test_the_local_day_and_window() -> None:
    n = DEFAULTS["nudge_hydrate"]
    assert schedule.local_day(at_ist(MONDAY, "00:10"), "Asia/Kolkata") == MONDAY
    assert schedule.in_window(n, at_ist(MONDAY, "09:30"), IST)
    assert not schedule.in_window(n, at_ist(MONDAY, "18:30"), IST)
    assert not schedule.in_window(n, at_ist(SUNDAY, "12:00"), IST)
    assert schedule.zone("Not/AZone").key == "Asia/Kolkata"
