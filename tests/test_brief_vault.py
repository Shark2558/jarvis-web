# tests/test_brief_vault.py -- R2 D5: the brief's Documents section (deterministic, no AI,
# fails on its own, switchable, generic Gmail copy)
from __future__ import annotations

import datetime as dt
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from brief_fakes import OWNER_UID, BriefGoogle, connector, mail, ms, timed
from vault_fakes import PDF, make

from jarvis.brief.models import (
    BriefData,
    BriefSettings,
    SettingsPatch,
    VaultDueItem,
    VaultDueSection,
)
from jarvis.brief.render import inbox_text, render_text
from jarvis.brief.service import BriefService
from jarvis.brief.store import BriefStore
from jarvis.brief.summarize import build_input
from jarvis.brief.vault_due import VaultDueBrief
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog

IST = ZoneInfo("Asia/Kolkata")
DAY = date(2026, 11, 5)
NOW = dt.datetime(2026, 11, 5, 1, 30, tzinfo=dt.UTC)
TIERS = {t: f"mock-{t.value}" for t in ModelTier}
UID = OWNER_UID


async def seed(svc: Any, days: int, type_id: str, n: int, *, confirmed: bool = True) -> Any:
    item = (await svc.add_file(UID, PDF + str(n).encode(), type_hint=type_id)).item
    patch: dict[str, Any] = {"last4": "4821", "title": "Akash private title"}
    if confirmed:
        patch.update({"expires_on": (DAY + dt.timedelta(days=days)).isoformat(), "confirm": True})
    await svc.update(UID, item.id, patch)
    return item


async def test_only_confirmed_documents_due_within_90_days_or_expired_30() -> None:
    svc, _, _ = make()
    await seed(svc, 30, "passport", 1)
    await seed(svc, 89, "puc", 2)
    await seed(svc, 91, "pan", 3)
    await seed(svc, -29, "vehicle_insurance", 4)
    await seed(svc, -31, "health_insurance", 5)
    await seed(svc, 10, "driving_licence", 6, confirmed=False)
    sec = await VaultDueBrief(svc).section(UID, IST, DAY)
    assert sec is not None and sec.total == 3 and sec.state == "ok"
    assert [i.days_left for i in sec.items] == [-29, 30, 89]


async def test_the_record_holds_type_whose_and_date_only() -> None:
    svc, _, _ = make()
    h = await svc.add_holder(UID, "Anjali Rao")
    item = (await svc.add_file(UID, PDF + b"x", type_hint="passport", holder_id=h.id)).item
    await svc.update(UID, item.id, {"last4": "4821", "expires_on": "2026-12-12", "confirm": True})
    sec = await VaultDueBrief(svc).section(UID, IST, DAY)
    assert sec is not None
    dumped = sec.model_dump_json()
    assert sec.items[0] == VaultDueItem(
        type_label="Passport", whose="family", expires_on="2026-12-12", days_left=37
    )
    for needle in ("Anjali", "4821", "private", item.id):
        assert needle not in dumped


async def test_nothing_due_or_switched_off_is_absent() -> None:
    svc, _, _ = make()
    assert await VaultDueBrief(svc).section(UID, IST, DAY) is None
    await seed(svc, 5, "passport", 1)
    assert await VaultDueBrief(svc).section(UID, IST, DAY) is not None
    await svc.update_settings(UID, {"brief": False})
    assert await VaultDueBrief(svc).section(UID, IST, DAY) is None


async def test_at_most_five_lines_all_counted() -> None:
    svc, _, _ = make()
    for n in range(7):
        await seed(svc, 5 + n, "puc", n)
    sec = await VaultDueBrief(svc).section(UID, IST, DAY)
    assert sec is not None and sec.total == 7 and len(sec.items) == 5
    assert "and 2 more in your vault" in render_text(
        BriefData(date="2026-11-05", tz="UTC", vault=sec)
    )


def test_render_lines_states_and_absence() -> None:
    sec = VaultDueSection(
        total=3,
        items=(
            VaultDueItem(type_label="Passport", expires_on="2026-12-12", days_left=37),
            VaultDueItem(
                type_label="PUC certificate", whose="family", expires_on="2026-11-05", days_left=0
            ),
            VaultDueItem(type_label="Vehicle insurance", expires_on="2026-11-02", days_left=-3),
        ),
    )
    text = render_text(BriefData(date="2026-11-05", tz="UTC", vault=sec))
    assert "DOCUMENTS · 3 need attention" in text
    assert "Passport (you) · expires 12 Dec 2026 (in 37 days)" in text
    assert "PUC certificate (family) · expires today" in text
    assert "Vehicle insurance (you) · expired 3 days ago" in text
    assert "DOCUMENTS" not in render_text(BriefData(date="2026-11-05", tz="UTC"))
    bad = render_text(
        BriefData(date="2026-11-05", tz="UTC", vault=VaultDueSection(state="unavailable"))
    )
    assert "could not be read" in bad


def test_the_ai_summary_input_never_contains_documents() -> None:
    sec = VaultDueSection(
        total=1,
        items=(VaultDueItem(type_label="SECRET-DOC-TYPE", expires_on="2026-12-12", days_left=3),),
    )
    data = BriefData(date="2026-11-05", tz="UTC", vault=sec)
    assert "SECRET-DOC-TYPE" not in build_input(data, (), include_todo=True)


def test_gmail_copy_is_generic_unless_inbox_copy_is_on() -> None:
    sec = VaultDueSection(
        total=2,
        items=(
            VaultDueItem(type_label="Passport", expires_on="2026-12-12", days_left=37),
            VaultDueItem(type_label="PUC certificate", expires_on="2026-12-13", days_left=38),
        ),
    )
    data = BriefData(date="2026-11-05", tz="UTC", vault=sec)
    text = render_text(data)
    short = inbox_text(text, data)
    assert "2 documents in your vault need attention - open JARVIS." in short
    assert "Passport" not in short and "PUC" not in short
    assert short.count("DOCUMENTS") == 1
    full = BriefData(date="2026-11-05", tz="UTC", vault=sec.model_copy(update={"inbox_copy": True}))
    assert inbox_text(render_text(full), full) == render_text(full)
    one = BriefData(date="2026-11-05", tz="UTC", vault=sec.model_copy(update={"total": 1}))
    assert "1 document in your vault needs attention" in inbox_text(render_text(one), one)
    plain = BriefData(date="2026-11-05", tz="UTC")
    assert inbox_text("x", plain) == "x" and inbox_text("x", None) == "x"


def test_settings_default_on_and_patchable() -> None:
    assert BriefSettings().vault is True
    assert SettingsPatch.model_validate({"vault": False}).vault is False


class Boom:
    async def section(self, uid: str, tz: Any, day: date) -> Any:
        raise RuntimeError("vault down")


async def service(vault_due: Any) -> BriefService:
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
        vault_due=vault_due,
    )


async def test_the_brief_carries_the_section_and_the_setting_turns_it_off() -> None:
    svc, _, _ = make()
    await seed(svc, 20, "passport", 1)
    brief = await service(VaultDueBrief(svc))
    today = await brief.generate(UID, trigger="manual", force=True)
    assert today.brief is not None and today.brief.data is not None
    assert today.brief.data.vault is not None and today.brief.data.vault.total == 1
    assert "DOCUMENTS" in today.brief.text and today.brief.ai is None
    await brief.update_settings(UID, SettingsPatch(vault=False))
    again = await brief.generate(UID, trigger="manual", force=True)
    assert again.brief is not None and again.brief.data is not None
    assert again.brief.data.vault is None and "DOCUMENTS" not in again.brief.text
    assert (await brief.get_settings(UID)).vault is False


async def test_a_failing_vault_section_never_fails_the_brief() -> None:
    brief = await service(Boom())
    today = await brief.generate(UID, trigger="manual", force=True)
    assert today.brief is not None and today.brief.status == "ready"
    data = today.brief.data
    assert data is not None and data.sections_status.vault == "unavailable"
    assert data.vault is not None and data.vault.state == "unavailable"
    assert data.calendar.today  # the rest of the brief is untouched
