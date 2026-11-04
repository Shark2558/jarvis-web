# tests/test_brief_family.py -- R1 D15: the brief's "Family today" section.
from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from brief_fakes import OWNER_UID, BriefGoogle, connector, mail, ms, timed
from r1d_fakes import FamilyCalendars
from r1d_fakes import connector as cal_connector

from jarvis.brief.family_day import FamilyBrief
from jarvis.brief.models import (
    BriefData,
    FamilyEvent,
    FamilyMemberDay,
    FamilySection,
    SettingsPatch,
)
from jarvis.brief.render import render_text
from jarvis.brief.service import BriefService
from jarvis.brief.store import BriefStore
from jarvis.brief.summarize import build_input
from jarvis.family.service import FamilyService
from jarvis.family.store import FamilyStore
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog

IST = ZoneInfo("Asia/Kolkata")
DAY = date(2027, 1, 15)
NOW = datetime(2027, 1, 15, 1, 30, tzinfo=UTC)
TIERS = {t: f"mock-{t.value}" for t in ModelTier}
ANJALI, RAVI = "anjali@gmail.com", "ravi@gmail.com"


def ev(title: str, start: str, end: str) -> dict[str, Any]:
    return {
        "summary": title,
        "start": {"dateTime": f"{start}+05:30"},
        "end": {"dateTime": f"{end}+05:30"},
    }


async def family(
    fake: FamilyCalendars, members: list[tuple[str, str]], uid: str = "owner"
) -> FamilyService:
    svc = FamilyService(await cal_connector(fake.client(), uid=uid), FamilyStore(MemoryDocs()))
    for name, cid in members:
        await svc.add(uid, name, cid)
    return svc


async def test_no_members_means_no_section() -> None:
    svc = await family(FamilyCalendars(), [])
    assert await FamilyBrief(svc).section("owner", IST, DAY) is None


async def test_each_member_shows_their_day() -> None:
    fake = FamilyCalendars(
        roles={ANJALI: "reader", RAVI: "freeBusyReader"},
        events={ANJALI: [ev("Dentist", "2027-01-15T10:00:00", "2027-01-15T11:00:00")]},
        busy={RAVI: [("2027-01-15T04:30:00Z", "2027-01-15T05:30:00Z")]},
    )
    svc = await family(fake, [("Anjali", ANJALI), ("Ravi", RAVI)])
    sec = await FamilyBrief(svc).section("owner", IST, DAY)
    assert sec is not None and sec.state == "ok"
    anjali, ravi = sec.members
    assert anjali.events == (FamilyEvent(when="10:00", title="Dentist"),) and not anjali.busy_only
    assert ravi.busy_only is True and ravi.events == (FamilyEvent(when="10:00–11:00"),)


async def test_a_member_who_unshared_is_marked_and_the_others_still_show() -> None:
    fake = FamilyCalendars(roles={ANJALI: "reader", RAVI: "reader"})
    svc = await family(fake, [("Anjali", ANJALI), ("Ravi", RAVI)])
    del fake.roles[RAVI]
    sec = await FamilyBrief(svc).section("owner", IST, DAY)
    assert sec is not None
    assert [(m.name, m.unavailable) for m in sec.members] == [("Anjali", False), ("Ravi", True)]


def test_render_names_are_labels_and_titles_are_quoted_and_defanged() -> None:
    sec = FamilySection(
        members=(
            FamilyMemberDay(
                name="Anjali", events=(FamilyEvent(when="10:00", title="Pay at evil.example now"),)
            ),
            FamilyMemberDay(name="Ravi", busy_only=True, events=(FamilyEvent(when="10:00–11:00"),)),
            FamilyMemberDay(name="Meera"),
            FamilyMemberDay(name="Old", unavailable=True),
        )
    )
    text = render_text(BriefData(date="2027-01-15", tz="Asia/Kolkata", family=sec))
    assert "FAMILY TODAY" in text
    assert "    10:00  “Pay at evil[.]example now”" in text and "evil.example" not in text
    assert "Ravi (busy times only)" in text and "10:00–11:00  busy" in text
    assert "Meera: nothing today." in text and "Old: not shared with you any more." in text


def test_the_ai_summary_input_never_contains_family() -> None:
    sec = FamilySection(
        members=(
            FamilyMemberDay(name="Anjali", events=(FamilyEvent(when="10:00", title="SECRET"),)),
        )
    )
    data = BriefData(date="2027-01-15", tz="UTC", family=sec)
    assert "SECRET" not in build_input(data, (), include_todo=True)


class Boom:
    async def section(self, uid: str, tz: Any, day: date) -> FamilySection:
        raise RuntimeError("calendar down")


async def service(family_day: Any) -> BriefService:
    fake = BriefGoogle(
        events=[timed("e1", "Standup", "2027-01-15T09:30", "2027-01-15T10:00")],
        messages=[
            mail("m1", "Priya <p@x.com>", "Budget", internal_ms=ms("2027-01-15T06:40:00+05:30"))
        ],
    )
    spec = BrainSpec(
        id="b", label="B", provider=MockProvider(), tiers=TIERS, trains_on_content=False
    )
    return BriefService(
        store=BriefStore(MemoryDocs()),
        google=await connector(fake),
        brains=BrainRegistry([spec], default_id="b"),
        approvals=None,
        audit=AuditLog(),
        owners=[OWNER_UID],
        default_tz="Asia/Kolkata",
        clock=lambda: NOW,
        family_day=family_day,
    )


async def test_the_brief_has_the_section_only_with_members_and_the_setting_on() -> None:
    fake = FamilyCalendars(
        roles={ANJALI: "reader"},
        events={ANJALI: [ev("Dentist", "2027-01-15T10:00:00", "2027-01-15T11:00:00")]},
    )
    svc = await family(fake, [("Anjali", ANJALI)], uid=OWNER_UID)
    brief = await service(FamilyBrief(svc))
    today = await brief.generate(OWNER_UID, trigger="manual", force=True)
    assert today.brief is not None and today.brief.data is not None
    assert today.brief.data.family is not None and "FAMILY TODAY" in today.brief.text
    await brief.update_settings(OWNER_UID, SettingsPatch(family=False))
    off = await brief.generate(OWNER_UID, trigger="manual", force=True)
    assert off.brief is not None and off.brief.data is not None and off.brief.data.family is None
    assert off.settings.family is False

    empty = await service(FamilyBrief(await family(FamilyCalendars(), [], uid=OWNER_UID)))
    none = await empty.generate(OWNER_UID, trigger="manual", force=True)
    assert none.brief is not None and none.brief.data is not None and none.brief.data.family is None
    assert "FAMILY TODAY" not in none.brief.text


async def test_a_failing_family_read_never_fails_the_brief() -> None:
    today = await (await service(Boom())).generate(OWNER_UID, trigger="manual", force=True)
    assert today.status == "ready" and today.brief is not None and today.brief.data is not None
    assert today.brief.data.family == FamilySection(state="unavailable")
    assert today.brief.data.calendar.today and "calendar down" not in today.brief.text
