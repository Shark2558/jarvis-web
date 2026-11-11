# tests/test_r11_c_privacy.py -- R11 Part C's privacy row `helpers_wellbeing` (plan D17: section
# "Helpers", delete with the passkey) lists, exports and deletes the sealed log, his nudge settings,
# his free-time list and the claims; the export never holds a calendar title or the sealed blob.
# Also the brief's lines (fixed templates) and the log lines (never a count or his words).
from __future__ import annotations

import json
import logging
from datetime import UTC, date

import pytest
from r11_fakes import UID
from r11_fakes_c import FakeCalendar, Planned, at_ist, part, run_tool

from jarvis.helpers.kinds import PRIVACY_SECTION

TUESDAY = date(2026, 11, 10)


async def filled() -> object:
    cal = FakeCalendar(every_day=[Planned("Secret evening walk", "17:00", "17:45")])
    rig = part(calendar=cal, at=at_ist(TUESDAY, "18:00"))
    await run_tool(rig, "nudge_set", kind="water", on="true")
    await run_tool(rig, "nudge_set", kind="activity", on="true")
    await run_tool(rig, "nudge_water_log", glasses="3")
    await run_tool(rig, "freetime_add", text="Sketch", minutes="30")
    await rig.job("activity_check").run(())
    return rig


async def test_the_row_is_in_the_helpers_section_with_a_passkey_delete() -> None:
    rig = await filled()
    (row,) = rig.part.privacy  # type: ignore[attr-defined]
    view = await row.describe(UID)
    assert (view.id, view.section, view.delete) == ("helpers_wellbeing", PRIVACY_SECTION, "passkey")
    assert view.encrypted_by_jarvis is True and view.count == 2  # one day + his settings


async def test_the_export_is_the_log_opened_never_a_calendar_title_or_a_blob() -> None:
    rig = await filled()
    out = await rig.part.privacy[0].export(UID)  # type: ignore[attr-defined]
    text = json.dumps(out)
    assert out["log"][0]["glasses_of_water"] == 3
    assert out["log"][0]["planned_activities"] == [
        {"word": "walk", "at": "17:00", "outcome": "asked"}
    ]
    assert out["free_time_ideas"][0]["text"] == "Sketch" and "nudge_hydrate" in out["nudges"]
    assert "Secret" not in text and "blob" not in text


async def test_delete_removes_everything_and_every_nudge_is_off_again() -> None:
    rig = await filled()
    row = rig.part.privacy[0]  # type: ignore[attr-defined]
    assert await row.delete(UID) == 3  # the day, the settings, the claims
    svc = rig.part.services["service"]  # type: ignore[attr-defined]
    assert (await svc.settings(UID)).on_kinds() == ()
    assert (await row.describe(UID)).count == 0
    kept = rig.docs._data  # type: ignore[attr-defined]  # noqa: SLF001
    assert not [p for p in kept if "nudges/" in p or "wellbeing/" in p]


async def test_the_brief_says_what_is_on_and_yesterdays_log() -> None:
    rig = part(at=at_ist(date(2026, 11, 9), "12:00"))
    await run_tool(rig, "nudge_set", kind="water", on="true")
    await run_tool(rig, "nudge_set", kind="focus", on="true")
    await run_tool(rig, "nudge_water_log", glasses="4")
    (brief,) = rig.part.brief
    lines = await brief.lines(UID, UTC, TUESDAY)
    assert lines == [
        "Nudges today: drink water every 90 min, your top priority.",
        "Yesterday: 4 glasses of water, 0 stand-ups.",
    ]
    assert await brief.lines(UID, UTC, date(2026, 11, 15)) == []  # a Sunday: no nudges


async def test_no_log_line_carries_a_count_or_his_words(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    rig = await filled()
    rig.notifier.fail = True
    await rig.job("nudges").run(())
    logged = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    for needle in ("Sketch", "Secret", "glasses", "walk at"):
        assert needle not in logged
