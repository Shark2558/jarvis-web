# tests/test_brief_deliveries.py -- R1 D13: the brief's Deliveries section (deterministic, no AI,
# fails on its own, switchable) over the fixture order emails.
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from brief_fakes import OWNER_UID, BriefGoogle, connector, mail, ms, timed
from r1d_fakes import GmailFake
from r1d_fakes import connector as gmail_connector

from jarvis.brief.deliveries import DeliveriesBrief
from jarvis.brief.models import (
    BriefData,
    BriefRecord,
    BriefSettings,
    DeliveriesSection,
    DeliveryItem,
    SectionsStatus,
    SettingsPatch,
)
from jarvis.brief.render import render_text
from jarvis.brief.schedule import has_unavailable_section
from jarvis.brief.service import BriefService
from jarvis.brief.store import BriefStore
from jarvis.brief.summarize import build_input
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier
from jarvis.packages.tools import PackageScanner
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog

IST = ZoneInfo("Asia/Kolkata")
DAY = date(2026, 11, 5)
NOW = datetime(2026, 11, 5, 1, 30, tzinfo=UTC)  # 07:00 IST
DIR = Path(__file__).parent / "fixtures" / "package_mails"
TIERS = {t: f"mock-{t.value}" for t in ModelTier}


def inbox(*stems: str) -> GmailFake:
    mails: list[dict[str, Any]] = []
    for stem in stems:
        for i, m in enumerate(json.loads((DIR / f"{stem}.json").read_text())["mails"]):
            mails.append({**m, "id": f"{stem}_{i}"})
    return GmailFake(mails)


async def brief_for(*stems: str, uid: str = "owner") -> DeliveriesBrief:
    fake = inbox(*stems)
    return DeliveriesBrief(PackageScanner(await gmail_connector(fake.client(), uid=uid)))


async def test_open_parcels_and_those_delivered_today_are_shown() -> None:
    brief = await brief_for(
        "amazon_shipped", "flipkart_shipped_ekart", "instamart_delivered", "delhivery_out"
    )
    sec = await brief.section("owner", IST, DAY)
    assert sec.state == "ok" and sec.total == 4
    assert {i.status for i in sec.items} == {"shipped", "delivered", "out_for_delivery"}
    az = next(i for i in sec.items if i.carrier == "Amazon Logistics")
    assert (az.merchant, az.expected, az.status) == ("Amazon", "2026-11-09", "shipped")


async def test_a_parcel_delivered_on_an_earlier_day_is_left_out() -> None:
    brief = await brief_for("amazon_delivered")
    assert (await brief.section("owner", IST, date(2026, 11, 20))).total == 0
    assert (await brief.section("owner", IST, DAY)).total == 1


async def test_cancelled_and_returned_parcels_are_not_deliveries() -> None:
    brief = await brief_for("myntra_cancelled", "myntra_return")
    assert (await brief.section("owner", IST, DAY)).total == 0


async def test_at_most_five_are_listed_but_all_are_counted() -> None:
    stems = [
        "amazon_shipped",
        "flipkart_shipped_ekart",
        "myntra_shipped_delhivery",
        "meesho_shipped_shadowfax",
        "delhivery_out",
        "bluedart_dispatched",
        "dtdc_in_transit",
    ]
    sec = await (await brief_for(*stems)).section("owner", IST, DAY)
    assert len(sec.items) == 5 and sec.total == 7


def test_render_quotes_and_defangs_the_subject_and_has_no_ai_label() -> None:
    sec = DeliveriesSection(
        total=1,
        items=(
            DeliveryItem(
                item="Shipped: visit evil.example/pay now",
                status="shipped",
                merchant="Amazon",
                carrier="Amazon Logistics",
                expected="2026-11-09",
            ),
        ),
    )
    data = BriefData(date="2026-11-05", tz="Asia/Kolkata", deliveries=sec)
    text = render_text(data)
    assert "DELIVERIES · 1 on the way or just delivered" in text
    assert "Shipped · “Shipped: visit evil[.]example/pay now” · Amazon" in text
    assert "expected Mon 09 Nov" in text and "evil.example" not in text


def test_render_states_and_empty() -> None:
    for state, word in (("unavailable", "could not be read"), ("not_connected", "not connected")):
        d = BriefData(
            date="2026-11-05",
            tz="UTC",
            deliveries=DeliveriesSection(state=state),  # type: ignore[arg-type]
        )
        assert word in render_text(d)
    empty = BriefData(date="2026-11-05", tz="UTC", deliveries=DeliveriesSection())
    assert "No parcels on the way." in render_text(empty)
    assert "DELIVERIES" not in render_text(BriefData(date="2026-11-05", tz="UTC"))


def test_the_ai_summary_input_never_contains_deliveries() -> None:
    sec = DeliveriesSection(
        total=1, items=(DeliveryItem(item="SECRET-PARCEL-SUBJECT", status="shipped"),)
    )
    data = BriefData(date="2026-11-05", tz="UTC", deliveries=sec)
    assert "SECRET-PARCEL-SUBJECT" not in build_input(data, (), include_todo=True)


# ---- through the service ---------------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.at = NOW

    def __call__(self) -> datetime:
        return self.at


class Boom:
    async def section(self, uid: str, tz: Any, day: date) -> DeliveriesSection:
        raise RuntimeError("gmail down")


async def service(deliveries: Any, clock: Clock | None = None) -> BriefService:
    fake = BriefGoogle(
        events=[timed("e1", "Standup", "2026-11-05T09:30", "2026-11-05T10:00")],
        messages=[
            mail("m1", "Priya <p@x.com>", "Budget", internal_ms=ms("2026-11-05T06:40:00+05:30"))
        ],
    )
    provider = MockProvider()
    spec = BrainSpec(id="b", label="B", provider=provider, tiers=TIERS, trains_on_content=False)
    return BriefService(
        store=BriefStore(MemoryDocs()),
        google=await connector(fake),
        brains=BrainRegistry([spec], default_id="b"),
        approvals=None,
        audit=AuditLog(),
        owners=[OWNER_UID],
        default_tz="Asia/Kolkata",
        clock=clock or Clock(),
        deliveries=deliveries,
    )


async def test_the_brief_carries_the_section_and_the_setting_turns_it_off() -> None:
    svc = await service(await brief_for("amazon_shipped", uid=OWNER_UID))
    today = await svc.generate(OWNER_UID, trigger="manual", force=True)
    assert today.brief is not None and today.brief.data is not None
    assert today.brief.data.deliveries is not None and today.brief.data.deliveries.total == 1
    assert "DELIVERIES" in today.brief.text and today.settings.deliveries is True
    await svc.update_settings(OWNER_UID, SettingsPatch(deliveries=False))
    again = await svc.generate(OWNER_UID, trigger="manual", force=True)
    assert again.brief is not None and again.brief.data is not None
    assert again.brief.data.deliveries is None and "DELIVERIES" not in again.brief.text
    assert again.settings.deliveries is False


async def test_a_failing_deliveries_read_never_fails_the_brief() -> None:
    svc = await service(Boom())
    today = await svc.generate(OWNER_UID, trigger="manual", force=True)
    assert today.status == "ready" and today.brief is not None and today.brief.data is not None
    assert today.brief.data.deliveries == DeliveriesSection(state="unavailable")
    assert today.brief.data.calendar.today  # the rest of the brief is intact
    assert "gmail down" not in today.brief.text


def test_settings_default_on() -> None:
    s = BriefSettings()
    assert s.deliveries is True and s.family is True


# ---- R1 fix-4 M3: retries and the ready alert ---------------------------------------------


async def test_an_unavailable_deliveries_section_is_retried_and_alerts_once() -> None:
    clock = Clock()
    svc = await service(Boom(), clock)
    await svc.update_settings(OWNER_UID, SettingsPatch(enabled=True))
    told: list[str] = []

    async def hook(uid: str) -> None:
        told.append(uid)

    svc.ready_hook = hook
    first = await svc.tick()
    assert first.generated == 1
    stored = await svc._store.get_brief(OWNER_UID, DAY.isoformat())
    assert stored is not None and stored.data is not None
    assert stored.data.sections_status.deliveries == "unavailable"
    clock.at = NOW + timedelta(minutes=30)
    second = await svc.tick()
    assert second.generated == 1  # retried: the new section was unavailable
    assert told == [OWNER_UID]  # but "ready" was announced only for the first record


def test_an_unavailable_family_section_is_retryable() -> None:
    data = BriefData(
        date="2026-11-05", tz="UTC", sections_status=SectionsStatus(family="unavailable")
    )
    rec = BriefRecord.model_validate(
        {
            "user_id": "u",
            "date": "2026-11-05",
            "tz": "UTC",
            "status": "ready",
            "claim_id": "c",
            "claimed_at": NOW,
            "trigger": "scheduled",
            "data": data.model_dump(),
        }
    )
    assert has_unavailable_section(rec)


def test_an_old_stored_status_without_the_new_fields_still_loads() -> None:
    st = SectionsStatus.model_validate({"calendar": "ok", "inbox": "ok", "jarvis": "ok"})
    assert st.deliveries == "ok" and st.family == "ok"


# ---- review slice 3 item 7: someone else's code in a subject never reaches the brief ----------

OTP_MAIL = {
    "id": "otp1",
    "from": "Amazon.in <shipment-tracking@amazon.in>",
    "subject": "Out for delivery: share OTP 482913 with the agent. Call +91 98765 43210",
    "date": "Thu, 05 Nov 2026 09:00:00 +0530",
    "body": "Amazon Transport Reference ID: TBA123456789012\nOut for delivery today",
}


async def test_a_code_in_the_subject_is_withheld_before_the_section_is_stored() -> None:
    brief = DeliveriesBrief(PackageScanner(await gmail_connector(GmailFake([OTP_MAIL]).client())))
    sec = await brief.section("owner", IST, DAY)
    (it,) = sec.items
    assert "482913" not in it.item and "98765" not in it.item and "OTP" not in it.item
    assert it.item == "(withheld - open it on screen)"
    assert it.status == "out_for_delivery" and it.carrier == "Amazon Logistics"


def test_a_stored_section_with_a_code_is_withheld_again_when_rendered() -> None:
    sec = DeliveriesSection(
        total=1,
        items=(DeliveryItem(item="Your OTP 12|34|56", status="shipped", merchant="Amazon"),),
    )
    text = render_text(BriefData(date="2026-11-05", tz="UTC", deliveries=sec))
    assert "12|34|56" not in text and "OTP" not in text and "withheld" in text
    assert "Shipped" in text and "Amazon" in text


def test_a_plain_subject_is_still_shown() -> None:
    sec = DeliveriesSection(
        total=1, items=(DeliveryItem(item="Shipped: boAt Airdopes 141", status="shipped"),)
    )
    data = BriefData(date="2026-11-05", tz="UTC", deliveries=sec)
    assert "boAt Airdopes 141" in render_text(data)
