# tests/test_brief_reminders.py — slice 11 B (D4): the morning brief labels JARVIS reminders as
# reminders, and a reminder is never a "clash" or busy time. Written before the implementation.
from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

from brief_fakes import timed

from jarvis.brief.collect import shape_calendar
from jarvis.brief.models import (
    BriefData,
    BriefEvent,
    CalendarSection,
    InboxSection,
    JarvisSection,
    SectionsStatus,
)
from jarvis.brief.render import event_line, render_text
from jarvis.brief.summarize import build_input

IST = ZoneInfo("Asia/Kolkata")
DAY = date(2027, 1, 15)
TAG = {"private": {"jarvis": "reminder"}}


def _reminder(eid: str, text: str, at: str) -> dict[str, object]:
    h, m = at[-5:].split(":")
    end = f"{at[:-5]}{h}:{int(m) + 5:02d}"
    return timed(eid, text, at, end, transparency="transparent", extendedProperties=TAG)


def test_a_tagged_reminder_is_labelled_and_never_clashes_or_blocks_time() -> None:
    cal = shape_calendar(
        [
            timed("e1", "Budget review", "2027-01-15T15:00", "2027-01-15T16:00"),
            _reminder("r1", "⏰ call Ravi", "2027-01-15T15:00"),
            timed("e2", "1:1 Priya", "2027-01-15T15:30", "2027-01-15T16:30"),
        ],
        IST,
        DAY,
    )
    by_title = {e.title: e for e in cal.today}
    rem = by_title["call Ravi"]  # the ⏰ prefix is dropped: the label says it
    assert rem.reminder is True and rem.start == "15:00" and rem.overlaps_with == ()
    assert by_title["Budget review"].reminder is False
    assert by_title["Budget review"].overlaps_with == ("1:1 Priya",)  # the real clash stays
    assert cal.clashes == 1
    assert ("09:00", "15:00") in {(b.start, b.end) for b in cal.free_blocks}


def test_an_untagged_event_with_an_alarm_clock_in_its_title_is_not_a_reminder() -> None:
    cal = shape_calendar(
        [timed("e1", "⏰ Wake-up call", "2027-01-15T07:00", "2027-01-15T07:30")], IST, DAY
    )
    assert cal.today[0].reminder is False and cal.today[0].title == "⏰ Wake-up call"


def test_text_brief_and_ai_input_show_a_reminder_as_one_with_its_time() -> None:
    e = BriefEvent(title="call Ravi", start="17:00", end="17:05", reminder=True)
    line = event_line(e)
    assert line.startswith("17:00  Reminder: “call Ravi”")
    assert "17:05" not in line
    data = BriefData(
        date="2027-01-15",
        tz="Asia/Kolkata",
        calendar=CalendarSection(today=(e,)),
        inbox=InboxSection(),
        jarvis=JarvisSection(),
        sections_status=SectionsStatus(calendar="ok", inbox="ok", jarvis="ok"),
    )
    assert "17:00  Reminder: “call Ravi”" in render_text(data)
    assert "- 17:00 | Reminder: call Ravi" in build_input(data, ())


def test_an_old_brief_without_the_field_reads_as_no_reminder() -> None:
    old = BriefEvent.model_validate({"title": "Standup", "start": "09:30", "end": "10:00"})
    assert old.reminder is False
    assert event_line(old).startswith("09:30–10:00  “Standup”")
