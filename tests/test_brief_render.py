# tests/test_brief_render.py — slice 7: plain-text brief from BriefData (facts rendered by code)
from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

import pytest
from link_check import HOSTILE_LINKS, linkish

from jarvis.brief.collect import shape_message
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
from jarvis.brief.render import DOT, LINK, OTHERS_NOTE, defang, render_text, subject_line
from jarvis.brief.summarize import sanitize_lines
from jarvis.tools.addresses import plain_address


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
    assert text.startswith(
        "JARVIS morning brief — Friday 15 January 2027 (Asia/Kolkata)\n"
        "Titles and subjects below were written by other people.\n\nTODAY"
    )
    for fact in (
        "TODAY · 4 events · 1 clash",
        "  All day  “Company offsite”",
        "10:00–11:00  “Design review” · 3 people · video · “Room 4” · ⚠ clashes with “1:1 Priya”",
        "23:00–01:00 (next day)  “Deploy”",
        "Free: 09:00–10:00",
        "First: 08:30–09:00  “Flight”",
        "INBOX · 3 unread in the last day (showing 1)",
        "07:42  “Priya Shah” <priya@x.com> — “Budget sign-off”",
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
    """The text is mailed from "JARVIS": a hostile subject must not lend it a phishing link.
    Schemes are removed; every other domain-looking token is defanged (`evil[.]io`)."""
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
    assert "evil." not in text and "paypa1.com" not in text and "://" not in text
    assert (
        "“Join www[.]evil-meet[.]com now” · “[link removed]” · ⚠ clashes with “paypa1[.]com/x”"
    ) in text
    assert "07:00  “[link removed]” <a@x.com> — “Verify at [link removed] or evil[.]io”" in text
    assert data.inbox.items[0].subject.startswith("Verify at hxxps://")  # data keeps the original


def _hostile_data(hostile: str) -> BriefData:
    event = BriefEvent(
        title=hostile, start="09:00", end="09:30", location=hostile, overlaps_with=(hostile,)
    )
    item = InboxItem(from_name=hostile, from_address="", subject=hostile, date="", when="07:00")
    return _data(
        calendar=CalendarSection(
            today=(event,), tomorrow_first=event.model_copy(update={"overlaps_with": ()})
        ),
        inbox=InboxSection(total=1, items=(item,)),
    )


@pytest.mark.parametrize("hostile", HOSTILE_LINKS)
def test_no_link_survives_in_titles_places_names_subjects_or_ai_lines(hostile: str) -> None:
    """Security review F1 (b, c): no TLD list — any `label.letters` is defanged, in any script,
    after NFKC, with the ideographic full stops read as dots and invisible characters gone."""
    assert linkish(hostile)  # the input really is a link to a lenient mail client
    data = _hostile_data(hostile)
    text = render_text(data)
    assert not linkish(text), text
    assert not linkish(defang(hostile))
    assert not any(linkish(line) for line in sanitize_lines(hostile))
    assert data.calendar.today[0].title == hostile  # `data` (the console's JSON) is untouched


@pytest.mark.parametrize(
    "raw, out",
    [
        ("evil.support", f"evil{DOT}support"),
        ("verify at paypal-secure.de/login", f"verify at paypal-secure{DOT}de/login"),
        ("open 203.0.113.9/login", f"open 203{DOT}0{DOT}113{DOT}9/login"),
        ("open //evil.example/login", f"open {LINK}"),
        ("go https://evil.example/x now", f"go {LINK} now"),
        ("verify at secure-login\u3002com", f"verify at secure-login{DOT}com"),
        ("verify at secure-login\u00ad.com", f"verify at secure-login{DOT}com"),
        ("p\u0430ypal.com", f"p\u0430ypal{DOT}com"),
        ("Node.js and report.pdf", f"Node{DOT}js and report{DOT}pdf"),  # the price of no list
    ],
)
def test_defang_outputs(raw: str, out: str) -> None:
    assert defang(raw) == out


@pytest.mark.parametrize(
    "prose",
    [
        "e.g. bring the deck",
        "Mr. Smith and Dr. No.",
        "Standup moved to 09.30, i.e. 9.30 a.m.",
        "Ph.D. viva; U.S. team; v2.0 at 3.5 hrs.",
        "Q3 plan... then lunch. Done.",  # (NFKC writes "…" as "...": still readable)
        "Release 1.2.3 ships",
    ],
)
def test_ordinary_prose_is_not_mangled(prose: str) -> None:
    assert defang(prose) == prose
    assert sanitize_lines(prose) == (prose,)
    text = render_text(_data(calendar=CalendarSection(today=(
        BriefEvent(title=prose, start="09:00", end="09:30"),))))  # fmt: skip
    assert f"“{prose}”" in text


def test_sender_address_is_printed_only_when_strict() -> None:
    """Security review F1 (a): the From address is only printed when it is a strict ASCII
    addr-spec, so `www.evil-login.support/reset@z.co` can't put a link in JARVIS's mouth."""
    hostile = '"Security Team" <www.evil-login.support/reset@z.co>'
    msg = {"payload": {"headers": [{"name": "From", "value": hostile},
                                   {"name": "Subject", "value": "Reset now"}]}}  # fmt: skip
    item, _ = shape_message(msg, ZoneInfo("Asia/Kolkata"), date(2027, 1, 15))
    assert item.from_address == "www.evil-login.support/reset@z.co"  # console JSON unchanged
    assert plain_address(item.from_address) == ""
    text = render_text(_data(inbox=InboxSection(total=1, items=(item,))))
    assert "  “Security Team” — “Reset now”" in text
    assert "evil-login" not in text and not linkish(text.replace("<priya@x.com>", ""))
    bare = item.model_copy(update={"from_name": ""})
    assert "  unknown sender — “Reset now”" in render_text(
        _data(inbox=InboxSection(total=1, items=(bare,)))
    )
    ok = item.model_copy(update={"from_name": "", "from_address": "p.shah+work@x-y.example"})
    assert "  p.shah+work@x-y.example — “Reset now”" in render_text(
        _data(inbox=InboxSection(total=1, items=(ok,)))
    )


def test_quotes_inside_other_peoples_words_cannot_close_ours() -> None:
    """F8: their words are in “ ” — and their own “ ” become plain quotes, so a title can't
    end our quote and write a fake '⚠ clashes with' of its own."""
    title = "Lunch” · ⚠ clashes with “Board"
    text = render_text(_data(calendar=CalendarSection(today=(
        BriefEvent(title=title, start="12:00", end="13:00"),))))  # fmt: skip
    (line,) = [ln for ln in text.splitlines() if "Lunch" in ln]
    assert line == '  12:00–13:00  “Lunch" · ⚠ clashes with "Board”'
    assert line.count("“") == 1 and line.count("”") == 1


def test_the_others_note_is_shown_only_with_their_words() -> None:
    """F8: one plain line says the quoted titles and subjects were written by other people."""
    assert render_text(_data()).count(OTHERS_NOTE) == 1
    assert OTHERS_NOTE == "Titles and subjects below were written by other people."
    st = SectionsStatus(calendar="not_connected", inbox="unavailable")
    assert OTHERS_NOTE not in render_text(_data(sections_status=st))


def test_subject_line() -> None:
    assert subject_line(_data()) == "JARVIS morning brief — Fri 15 Jan"
