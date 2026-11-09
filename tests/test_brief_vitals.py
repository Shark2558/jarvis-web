# tests/test_brief_vitals.py -- R4 I1 (W10): the brief's Vitals section (api/r4_wiring.VitalsBrief
# over vitals.brief.vitals_lines): deterministic, omitted when empty, never in the AI-summary
# input, fails on its own, rendered as its own block.
from __future__ import annotations

import datetime as dt
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from brief_fakes import OWNER_UID, BriefGoogle, connector, mail, ms, timed
from vitals_fakes import UID as VUID
from vitals_fakes import FakeBilling, Rig, key

from jarvis.api.r4_wiring import VitalsBrief
from jarvis.brief.models import BriefData, SectionsStatus, VitalsSection
from jarvis.brief.render import render_text
from jarvis.brief.service import BriefService
from jarvis.brief.store import BriefStore
from jarvis.brief.summarize import build_input
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog

IST = ZoneInfo("Asia/Kolkata")
DAY = date(2026, 11, 5)
NOW = dt.datetime(2026, 11, 5, 1, 30, tzinfo=dt.UTC)
TIERS = {t: f"mock-{t.value}" for t in ModelTier}


async def test_section_carries_the_lines_and_is_absent_when_there_are_none() -> None:
    rig = Rig()
    await rig.svc.set_key(VUID, key("a", label="Alpha key", limit=10, used=9))
    sec = await VitalsBrief(rig.svc).section(VUID, IST, DAY)
    assert sec is not None and sec.state == "ok"
    assert sec.lines[0].startswith("Amber: Alpha key")
    assert sec.lines[-1].startswith("AI spend: ₹")
    empty = await VitalsBrief(Rig(billing=FakeBilling(down=True)).svc).section(VUID, IST, DAY)
    assert empty is None  # nothing readable: the section is simply left out


def test_render_block_states_and_absence() -> None:
    sec = VitalsSection(lines=("Red: Beta key expired", "AI spend: ₹120 of ₹500 this month"))
    text = render_text(BriefData(date="2026-11-05", tz="UTC", vitals=sec))
    assert "VITALS\n  Red: Beta key expired\n  AI spend: ₹120 of ₹500 this month" in text
    assert "VITALS" not in render_text(BriefData(date="2026-11-05", tz="UTC"))
    bad = render_text(
        BriefData(date="2026-11-05", tz="UTC", vitals=VitalsSection(state="unavailable"))
    )
    assert "VITALS" in bad and "could not be read" in bad


def test_the_ai_summary_input_never_contains_the_vitals_section() -> None:
    sec = VitalsSection(lines=("Red: SECRET-VITALS-LABEL expired",))
    data = BriefData(date="2026-11-05", tz="UTC", vitals=sec)
    assert "SECRET-VITALS" not in build_input(data, (), include_todo=True)


def test_old_records_without_the_section_still_load() -> None:
    data = BriefData.model_validate({"date": "2026-11-05", "tz": "UTC"})
    assert data.vitals is None and data.sections_status.vitals == "ok"
    assert SectionsStatus().vitals == "ok"


class Boom:
    async def section(self, uid: str, tz: Any, day: date) -> VitalsSection | None:
        raise RuntimeError("store down")


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
        owners=[OWNER_UID],
        default_tz="Asia/Kolkata",
        clock=lambda: NOW,
        vitals=section,
    )


async def test_the_brief_carries_the_section() -> None:
    rig = Rig()
    await rig.svc.set_key(OWNER_UID, key("a", label="Alpha key", expires_in_days=-1))
    brief = await service(VitalsBrief(rig.svc))
    today = await brief.generate(OWNER_UID, trigger="manual", force=True)
    assert today.brief is not None and today.brief.data is not None
    assert today.brief.data.vitals is not None
    assert today.brief.data.vitals.lines[0].startswith("Red: Alpha key")
    assert "VITALS" in today.brief.text and today.brief.ai is None


async def test_a_failing_vitals_section_never_fails_the_brief() -> None:
    today = await (await service(Boom())).generate(OWNER_UID, trigger="manual", force=True)
    assert today.brief is not None and today.brief.status == "ready"
    data = today.brief.data
    assert data is not None and data.sections_status.vitals == "unavailable"
    assert data.calendar.today
