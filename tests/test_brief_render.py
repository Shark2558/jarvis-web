# tests/test_brief_render.py — slice 7: plain-text brief from BriefData (facts rendered by code)
from __future__ import annotations

from jarvis.brief.models import (
    AI_LABEL,
    AIBlock,
    BriefData,
    BriefEvent,
    CalendarSection,
    FreeBlock,
    InboxItem,
    InboxSection,
    JarvisSection,
    SectionsStatus,
)
from jarvis.brief.render import render_text, subject_line


def _data(**over: object) -> BriefData:
    base: dict[str, object] = {
        "date": "2027-01-15",
        "tz": "Asia/Kolkata",
        "calendar": CalendarSection(
            today=(
                BriefEvent(title="Company offsite", start="", end="", all_day=True),
                BriefEvent(
                    title="Design review",
                    start="10:00",
                    end="11:00",
                    attendees=3,
                    has_video=True,
                    location="Room 4",
                    overlaps_with=("1:1 Priya",),
                ),
                BriefEvent(
                    title="1:1 Priya", start="10:30", end="11:30", overlaps_with=("Design review",)
                ),
                BriefEvent(title="Deploy", start="23:00", end="01:00", ends_later=True),
            ),
            clashes=1,
            free_blocks=(FreeBlock(start="09:00", end="10:00", minutes=60),),
            tomorrow_first=BriefEvent(title="Flight", start="08:30", end="09:00"),
        ),
        "inbox": InboxSection(
            total=3,
            items=(
                InboxItem(
                    from_name="Priya Shah",
                    from_address="priya@x.com",
                    subject="Budget sign-off",
                    date="",
                    when="07:42",
                ),
            ),
        ),
        "jarvis": JarvisSection(approvals_waiting=1),
    }
    base.update(over)
    return BriefData.model_validate(base)


def test_full_brief_renders_every_fact() -> None:
    text = render_text(_data())
    assert text.startswith("JARVIS morning brief — Friday 15 January 2027 (Asia/Kolkata)")
    for fact in (
        "TODAY · 4 events · 1 clash",
        "All day",
        "Company offsite",
        "10:00–11:00  Design review · 3 people · video · Room 4 · ⚠ clashes with 1:1 Priya",
        "23:00–01:00 (next day)  Deploy",
        "Free: 09:00–10:00",
        "First: 08:30–09:00  Flight",
        "INBOX · 3 unread in the last day (showing 1)",
        "07:42  Priya Shah <priya@x.com> — Budget sign-off",
        "1 approval waiting for you in the console.",
    ):
        assert fact in text, fact
    assert "AI summary" not in text


def test_empty_sections_say_so() -> None:
    text = render_text(
        _data(calendar=CalendarSection(), inbox=InboxSection(), jarvis=JarvisSection())
    )
    assert "Nothing on the calendar today." in text
    assert "Nothing yet tomorrow." in text
    assert "No unread mail in the last day." in text and "No approvals waiting." in text


def test_not_connected_and_unavailable_are_explained() -> None:
    st = SectionsStatus(calendar="not_connected", inbox="unavailable", jarvis="ok")
    text = render_text(_data(calendar=CalendarSection(), inbox=InboxSection(), sections_status=st))
    assert "Google is not connected" in text and "Integrations" in text
    assert "Your inbox could not be read just now." in text
    assert "Nothing on the calendar today." not in text


def test_ai_section_is_labelled_and_last_so_facts_are_unchanged() -> None:
    data = _data()
    plain = render_text(data)
    ai = render_text(data, AIBlock(lines=("Clash at 10:30.", "Reply to Priya."), model="m"))
    assert ai.startswith(plain)
    tail = ai[len(plain) :]
    assert AI_LABEL in tail and "• Clash at 10:30." in tail and "• Reply to Priya." in tail
    noted = render_text(data, None, "Daily AI summary limit reached.")
    assert noted.startswith(plain) and "Daily AI summary limit reached." in noted


def test_links_in_other_peoples_words_are_not_clickable_in_the_text() -> None:
    """The text is mailed from "JARVIS": a hostile subject must not lend it a phishing link."""
    data = _data(
        calendar=CalendarSection(
            today=(
                BriefEvent(title="Join www.evil-meet.com now", start="09:00", end="09:30",
                           location="https://evil.example/room", overlaps_with=("paypa1.com/x",)),
            )
        ),
        inbox=InboxSection(
            total=1,
            items=(InboxItem(from_name="https://evil.example", from_address="a@x.com",
                             subject="Verify at hxxps://evil.example/v or evil.io", date="",
                             when="07:00"),),
        ),
    )  # fmt: skip
    text = render_text(data)
    assert "evil" not in text and "paypa1" not in text
    assert "Join [link removed] now · [link removed] · ⚠ clashes with [link removed]" in text
    assert "07:00  [link removed] <a@x.com> — Verify at [link removed] or [link removed]" in text
    assert data.inbox.items[0].subject.startswith("Verify at hxxps://")  # data keeps the original


def test_subject_line() -> None:
    assert subject_line(_data()) == "JARVIS morning brief — Fri 15 Jan"
