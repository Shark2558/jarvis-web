# tests/test_brief_home.py -- R3 B: the brief's "Home overnight" section (deterministic, no AI, no
# name, counts and times, fails on its own, switchable, absent when nothing happened).
from __future__ import annotations

import datetime as dt
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from brief_fakes import OWNER_UID, BriefGoogle, connector, mail, ms, timed
from camera_fakes import PERSON, Rig, rig

from jarvis.brief.home_overnight import HomeOvernightBrief
from jarvis.brief.models import (
    BriefData,
    BriefSettings,
    HomeOvernightItem,
    HomeOvernightSection,
    SectionsStatus,
    SettingsPatch,
)
from jarvis.brief.render import render_text
from jarvis.brief.service import BriefService
from jarvis.brief.store import BriefStore
from jarvis.brief.summarize import build_input
from jarvis.camera.models import FeedItem
from jarvis.faces.ports import Resolved
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog

IST = ZoneInfo("Asia/Kolkata")
DAY = date(2026, 11, 5)
NOW = dt.datetime(2026, 11, 5, 1, 30, tzinfo=dt.UTC)  # 07:00 IST
TIERS = {t: f"mock-{t.value}" for t in ModelTier}
UID = OWNER_UID


def at(h: int, m: int, day: int = 4) -> float:
    return dt.datetime(2026, 11, day, h, m, tzinfo=IST).timestamp()


async def home(items: list[FeedItem]) -> tuple[Rig, HomeOvernightBrief]:
    r = await rig()
    r.clock.now = NOW.timestamp()
    for i in items:
        await r.feed.add(UID, i)
    return r, HomeOvernightBrief(r.feed, r.config)


async def test_overnight_lines_counts_and_held() -> None:
    r, b = await home(
        [
            FeedItem(at=at(19, 0), kind="package", camera="gate", decision="ring"),  # before 20:00
            FeedItem(at=at(23, 30), kind="package", camera="gate", decision="held"),
            FeedItem(at=at(2, 10, 5), kind="intruder", camera="gate", decision="ring"),
            FeedItem(at=at(5, 40, 5), kind="greeting", camera="gate", person=PERSON, score=0.95),
            FeedItem(at=at(1, 0, 5), kind="other", camera="gate", label="car"),
        ]
    )
    sec = await b.section(UID, IST, DAY)
    assert sec is not None and sec.total == 3 and sec.held == 1
    assert [(i.when, i.words) for i in sec.items] == [
        ("23:30", "A package was left at Gate"),
        ("02:10", "Burglar alert at Gate"),
        ("05:40", "A person JARVIS recognised arrived at Gate"),
    ]


async def test_no_name_ever_reaches_the_section() -> None:
    r, b = await home(
        [FeedItem(at=at(5, 40, 5), kind="greeting", camera="gate", person=PERSON, score=0.95)]
    )
    r.faces.people[PERSON] = Resolved(name="Anjali", person=PERSON)
    sec = await b.section(UID, IST, DAY)
    assert (
        sec is not None
        and "Anjali" not in sec.model_dump_json()
        and PERSON not in sec.model_dump_json()
    )


async def test_nothing_overnight_is_absent() -> None:
    _, b = await home([FeedItem(at=at(1, 0, 5), kind="other", camera="gate", label="car")])
    assert await b.section(UID, IST, DAY) is None


async def test_at_most_five_lines_all_counted() -> None:
    _, b = await home([FeedItem(at=at(21, i), kind="package", camera="gate") for i in range(7)])
    sec = await b.section(UID, IST, DAY)
    assert sec is not None and sec.total == 7 and len(sec.items) == 5
    assert "and 2 more in the Home panel" in render_text(
        BriefData(date="2026-11-05", tz="UTC", home=sec)
    )


def test_render_states_and_absence() -> None:
    sec = HomeOvernightSection(
        total=2,
        held=1,
        items=(HomeOvernightItem(when="23:30", words="A package was left at Gate"),),
    )
    text = render_text(BriefData(date="2026-11-05", tz="UTC", home=sec))
    assert "HOME OVERNIGHT · 2 noted · 1 held for quiet hours" in text
    assert "  23:30  A package was left at Gate" in text
    assert "HOME OVERNIGHT" not in render_text(BriefData(date="2026-11-05", tz="UTC"))
    bad = render_text(
        BriefData(date="2026-11-05", tz="UTC", home=HomeOvernightSection(state="unavailable"))
    )
    assert "could not be read" in bad


def test_the_ai_summary_input_never_contains_the_home_section() -> None:
    sec = HomeOvernightSection(
        total=1, items=(HomeOvernightItem(when="02:10", words="SECRET-HOME"),)
    )
    assert "SECRET-HOME" not in build_input(
        BriefData(date="2026-11-05", tz="UTC", home=sec), (), include_todo=True
    )


def test_settings_default_on_patchable_and_old_records_load() -> None:
    assert BriefSettings().home is True
    assert SettingsPatch.model_validate({"home": False}).home is False
    assert SectionsStatus().home == "ok"
    assert BriefData.model_validate({"date": "2026-11-05", "tz": "UTC"}).home is None


class Boom:
    async def section(self, uid: str, tz: Any, day: date) -> Any:
        raise RuntimeError("home down")


async def service(section: Any) -> BriefService:
    fake = BriefGoogle(
        events=[timed("e1", "Standup", "2026-11-05T09:30", "2026-11-05T10:00")],
        messages=[
            mail("m1", "Priya <p@x.com>", "Budget", internal_ms=ms("2026-11-05T06:40:00+05:30"))
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
        owners=[UID],
        default_tz="Asia/Kolkata",
        clock=lambda: NOW,
        home_overnight=section,
    )


async def test_the_brief_carries_the_section_and_the_setting_turns_it_off() -> None:
    r, b = await home([FeedItem(at=at(23, 30), kind="package", camera="gate", decision="held")])
    brief = await service(b)
    today = await brief.generate(UID, trigger="manual", force=True)
    assert today.brief is not None and today.brief.data is not None
    assert today.brief.data.home is not None and today.brief.data.home.held == 1
    assert "HOME OVERNIGHT" in today.brief.text and today.brief.ai is None
    await brief.update_settings(UID, SettingsPatch(home=False))
    again = await brief.generate(UID, trigger="manual", force=True)
    assert again.brief is not None and again.brief.data is not None
    assert again.brief.data.home is None and "HOME OVERNIGHT" not in again.brief.text
    assert (await brief.get_settings(UID)).home is False


async def test_a_failing_home_section_never_fails_the_brief() -> None:
    today = await (await service(Boom())).generate(UID, trigger="manual", force=True)
    assert today.brief is not None and today.brief.status == "ready"
    data = today.brief.data
    assert data is not None and data.sections_status.home == "unavailable"
    assert data.calendar.today
