# tests/test_r11_c_tools.py -- R11 Part C's tools (plan D6, D16): `nudge_*` (row `nudges`) and
# `freetime_*` (row `household`), names inside the part's families, risks R1 for reads and R2 for
# changes, fixed Activity words, a card when the round read outside content for what keeps his
# words, snooze/stop/resume on the gate's own state, the sealed log off without a keyring.
from __future__ import annotations

from datetime import date

import pytest
from r11_fakes import UID
from r11_fakes_c import FakeCalendar, FakeRain, Planned, Rig, at_ist, part, run_tool

from jarvis.core.guardrails import ActionRisk
from jarvis.helpers.gate import GateStore
from jarvis.helpers.kinds import tool_allowed
from jarvis.helpers.nudges.store import OFF_WORDS
from jarvis.tools.taint import context_trust

TUESDAY = date(2026, 11, 10)
READS = {"nudge_status", "freetime_suggest", "freetime_list"}


def test_every_tool_is_in_the_parts_families_with_its_risk_and_fixed_activity_words() -> None:
    rig = part()
    names = [t.name for t in rig.part.tools]
    assert len(names) == len(set(names)) == 13
    for t in rig.part.tools:
        assert tool_allowed("nudges", t.name), t.name
        assert t.risk is (ActionRisk.READ_ONLY if t.name in READS else ActionRisk.REVERSIBLE)
        assert t.activity_words and "{" not in t.activity_words


async def test_set_switches_a_nudge_on_with_text_arguments_as_no_ai_sends_them() -> None:
    rig = part()
    out = await run_tool(rig, "nudge_set", kind="water", on="true", every_minutes="45")
    assert "Drink water: on, every 45 minutes, 09:30-18:30, Monday to Saturday." in out["spoken"]
    out = await run_tool(rig, "nudge_set", kind="standup", meeting=True, word="daily sync")
    assert "'daily sync' meeting" in out["spoken"]
    out = await run_tool(rig, "nudge_set", kind="focus", times="09:00, 14:00", days="weekdays")
    assert "at 09:00, 14:00, Monday to Friday" in out["spoken"]
    out = await run_tool(rig, "nudge_set", kind="activity", words="walk, swim")
    assert "for walk, swim" in out["spoken"]


@pytest.mark.parametrize(
    "args",
    [
        {"kind": "coffee", "on": "true"},
        {"kind": "all", "on": "true"},
        {"kind": "water"},
        {"kind": "water", "every_minutes": "5"},
        {"kind": "water", "on": "maybe"},
        {"kind": "water", "start": "19:00", "end": "08:00"},
        {"kind": "water", "days": "someday"},
    ],
)
async def test_set_refuses_what_it_cannot_do_in_plain_words(args: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        await run_tool(part(), "nudge_set", **args)


def test_what_keeps_his_words_is_a_card_when_the_round_read_outside_content() -> None:
    rig = part()
    for name in ("nudge_set", "freetime_add"):
        tool = rig.tool(name)
        assert tool.asks({}) is False
        with context_trust(untrusted=True):
            assert tool.asks({}) is True


async def test_snooze_stop_and_resume_change_the_gates_own_state() -> None:
    rig = part(at=at_ist(TUESDAY, "12:00"))
    gate = GateStore(rig.docs)
    out = await run_tool(rig, "nudge_snooze", kind="water", minutes="60")
    assert "for 60 minutes" in out["spoken"]
    assert "nudge_hydrate" in (await gate.state(UID)).snoozed
    await run_tool(rig, "nudge_snooze", kind="standup", until="tomorrow")
    assert (await gate.state(UID)).stopped_on("nudge_standup", "2026-11-10")
    out = await run_tool(rig, "nudge_stop", kind="all")
    assert "for today" in out["spoken"] and (await gate.state(UID)).stopped_on(
        "nudge_focus", "2026-11-10"
    )
    await run_tool(rig, "nudge_resume", kind="all")
    state = await gate.state(UID)
    assert state.snoozed == {} and state.stopped == {}
    with pytest.raises(ValueError):
        await run_tool(rig, "nudge_snooze", kind="water", minutes="5")


async def test_stop_for_good_switches_it_off_and_resume_says_so() -> None:
    rig = part()
    await run_tool(rig, "nudge_set", kind="water", on="true")
    out = await run_tool(rig, "nudge_stop", kind="water", for_good="true")
    assert "Switched off" in out["spoken"]
    svc = rig.part.services["service"]
    assert not (await svc.settings(UID)).nudge("nudge_hydrate").on
    out = await run_tool(rig, "nudge_resume", kind="water")
    assert "switched off, though" in out["spoken"]


async def test_the_water_and_stand_up_log_and_the_status() -> None:
    rig = part(at=at_ist(TUESDAY, "12:00"))
    await run_tool(rig, "nudge_set", kind="water", on="true")
    assert "1 glasses" in (await run_tool(rig, "nudge_water_log"))["spoken"]
    assert "3 glasses" in (await run_tool(rig, "nudge_water_log", glasses="2"))["spoken"]
    assert "1 stand-ups" in (await run_tool(rig, "nudge_standup_log"))["spoken"]
    out = await run_tool(rig, "nudge_status")
    assert "Today: 3 glasses of water, 1 stand-ups." in out["spoken"]
    assert out["on"] == ["nudge_hydrate"]


async def test_without_a_keyring_the_log_says_it_is_off() -> None:
    rig = part(sealed=False)
    for name, args in (
        ("nudge_water_log", {}),
        ("nudge_standup_log", {}),
        ("nudge_activity_checkin", {"word": "walk", "outcome": "done"}),
    ):
        assert (await run_tool(rig, name, **args))["spoken"] == OFF_WORDS
    assert "glasses" not in (await run_tool(rig, "nudge_status"))["spoken"]


async def test_a_check_in_must_be_one_of_his_activity_words() -> None:
    rig = part()
    out = await run_tool(rig, "nudge_activity_checkin", word="homework", outcome="done")
    assert "isn't one of your planned activities" in out["spoken"] and "walk" in out["spoken"]
    with pytest.raises(ValueError):
        await run_tool(rig, "nudge_activity_checkin", word="walk", outcome="maybe")


# ---- the free-time list --------------------------------------------------------------------------
async def ideas_rig() -> Rig:
    cal = FakeCalendar(every_day=[Planned("Call with a friend", "19:00", "19:30", own=False)])
    rig = part(calendar=cal, rain=FakeRain(rainy={TUESDAY}), at=at_ist(TUESDAY, "18:00"))
    await run_tool(rig, "freetime_add", text="Read a novel", minutes="45", place="indoor")
    await run_tool(rig, "freetime_add", text="Cycle by the lake", minutes="40", place="outside")
    return rig


async def test_add_list_done_and_remove_ideas() -> None:
    rig = await ideas_rig()
    listed = (await run_tool(rig, "freetime_list"))["spoken"]
    assert "Read a novel (45 min, indoor); Cycle by the lake (40 min, outdoor)" in listed
    assert "done today" in (await run_tool(rig, "freetime_done", text="novel"))["spoken"]
    svc = rig.part.services["service"]
    assert (await svc.settings(UID)).ideas[0].last_done == "2026-11-10"
    out = await run_tool(rig, "freetime_remove", text="cycle by the lake")
    assert "Removed" in out["spoken"]
    with pytest.raises(ValueError, match="isn't on your free-time list"):
        await run_tool(rig, "freetime_remove", text="skydiving")
    with pytest.raises(ValueError):
        await run_tool(rig, "freetime_add", text="", minutes="30")


async def test_suggest_picks_by_code_what_fits_and_avoids_rain() -> None:
    rig = await ideas_rig()
    out = await run_tool(rig, "freetime_suggest")
    assert out["idea"] == "Read a novel" and "about an hour" in out["spoken"]
    out = await run_tool(rig, "freetime_suggest", minutes="20")
    assert "Nothing on your list fits" in out["spoken"]


async def test_suggest_without_a_calendar_asks_for_minutes() -> None:
    rig = part(at=at_ist(TUESDAY, "18:00"))
    rig.part.services["service"].agenda._source = None  # noqa: SLF001 - Google not linked
    await run_tool(rig, "freetime_add", text="Sketch", minutes="30")
    assert "isn't linked" in (await run_tool(rig, "freetime_suggest"))["spoken"]
    out = await run_tool(rig, "freetime_suggest", minutes="30")
    assert out["idea"] == "Sketch"


async def test_stop_stand_up_for_good_also_switches_the_meeting_variant_off() -> None:
    rig = part()
    await run_tool(rig, "nudge_set", kind="standup", on="true", meeting="true")
    await run_tool(rig, "nudge_stop", kind="standup", for_good="true")
    up = (await rig.part.services["service"].settings(UID)).nudge("nudge_standup")
    assert (up.on, up.meeting) == (False, False)
