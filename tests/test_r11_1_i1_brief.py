# tests/test_r11_1_i1_brief.py -- R11.1 I1 reviews: the brief's mail reads obey the mail row.
# Security M1: the Deliveries section scanned the mailbox for shipping mail (full bodies) with
# no permission check, while the inbox section asked the "Search and read email" row. Now both
# go through `BackgroundReads.allowed`: with the row at Never or Ask first the WHOLE brief makes
# no Gmail request at all, from a refresh or from the clock job. Code M4: the brief then says the
# mail is paused by his Permissions, not that it "could not be read".
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from brief_fakes import OWNER_UID, BriefGoogle, connector, mail, ms, timed

from jarvis.brief.deliveries import DELIVERIES_TOOL, DeliveriesBrief
from jarvis.brief.models import SettingsPatch
from jarvis.brief.render import PAUSED
from jarvis.brief.service import BriefService
from jarvis.brief.store import BriefStore
from jarvis.core.guardrails import ConfirmationGate
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier
from jarvis.packages.tools import PackageScanner, packages_tools
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog
from jarvis.tools.background import BackgroundReads
from jarvis.tools.gateway import Gateway
from jarvis.tools.gmail_digest import inbox_tools
from jarvis.tools.policy import Effect, Policy, PolicyRule
from jarvis.tools.registry import ToolRegistry

NOW = datetime(2027, 1, 15, 1, 30, tzinfo=UTC)  # 07:00 in Asia/Kolkata: the brief's own time
TIERS = {t: f"mock-{t.value}" for t in ModelTier}


class _Rows:
    def __init__(self, effect: Effect | None) -> None:
        self.effect = effect

    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        if self.effect is None:
            return []
        return [PolicyRule(tool_pattern="gmail_*", effect=self.effect, source="owner")]


def _reads(conn: Any, effect: Effect | None) -> tuple[BackgroundReads, AuditLog]:
    """The app's path: BackgroundReads over a gateway whose rules are his rows."""
    reg = ToolRegistry()
    for t in [*inbox_tools(lambda: conn, max_reads=30), *packages_tools(conn)]:
        reg.register(t)
    audit = AuditLog()
    gw = Gateway(
        registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=audit, rules=_Rows(effect)
    )
    return BackgroundReads.of(gw), audit


async def _brief(effect: Effect | None) -> tuple[BriefService, BriefGoogle, AuditLog]:
    fake = BriefGoogle(
        events=[timed("e1", "Standup", "2027-01-15T09:30", "2027-01-15T10:00")],
        messages=[
            mail("m1", "Shop <orders@shop.example>", "Your order has shipped",
                 snippet="Your parcel is on its way", internal_ms=ms("2027-01-15T06:40:00+05:30")),
        ],
    )  # fmt: skip
    conn = await connector(fake)
    reads, audit = _reads(conn, effect)
    provider = MockProvider()
    spec = BrainSpec(id="b", label="B", provider=provider, tiers=TIERS)
    svc = BriefService(
        store=BriefStore(MemoryDocs()),
        google=conn,
        brains=BrainRegistry([spec], default_id="b"),
        approvals=None,
        audit=AuditLog(),
        owners=[OWNER_UID],
        default_tz="Asia/Kolkata",
        clock=lambda: NOW,
        reads=reads,
        deliveries=DeliveriesBrief(PackageScanner(conn), reads=reads),
    )
    await svc.update_settings(OWNER_UID, SettingsPatch(enabled=True, deliveries=True))
    return svc, fake, audit


def _gmail(fake: BriefGoogle) -> list[str]:
    return [f"{q.method} {q.url.path}" for q in fake.requests if "/gmail/" in q.url.path]


@pytest.mark.parametrize("effect", [Effect.DENY, Effect.ASK])
async def test_never_or_ask_first_means_the_whole_brief_reads_no_mail(effect: Effect) -> None:
    svc, fake, _ = await _brief(effect)

    ticked = await svc.tick()  # the clock job at his brief time
    refreshed = await svc.generate(OWNER_UID, trigger="manual", force=True)  # Refresh

    assert ticked.generated == 1
    assert _gmail(fake) == []  # neither the inbox nor the deliveries asked Gmail anything
    b = refreshed.brief
    assert b is not None and b.data is not None and b.data.deliveries is not None
    assert b.data.calendar.today[0].title == "Standup"  # the other sections are untouched
    assert b.data.sections_status.inbox == "paused" and b.data.deliveries.state == "paused"


@pytest.mark.parametrize("effect", [Effect.DENY, Effect.ASK])
async def test_a_paused_mail_row_is_said_as_paused_by_permissions(effect: Effect) -> None:
    svc, _, _ = await _brief(effect)

    view = await svc.generate(OWNER_UID, trigger="manual", force=True)

    assert view.brief is not None
    text = view.brief.text
    assert PAUSED.format("inbox") in text and PAUSED.format("deliveries") in text
    assert "could not be read" not in text and "Permissions" in PAUSED


async def test_with_the_row_on_allow_the_deliveries_read_mail_and_leave_an_audit_line() -> None:
    svc, fake, audit = await _brief(Effect.ALLOW)

    view = await svc.generate(OWNER_UID, trigger="manual", force=True)

    assert view.brief is not None and view.brief.data is not None
    deliveries = view.brief.data.deliveries
    assert deliveries is not None and deliveries.state == "ok"
    assert any("messages" in r for r in _gmail(fake))
    lines = [(e.tool, e.outcome) for e in audit._entries]  # noqa: SLF001
    assert (DELIVERIES_TOOL, "executed") in lines


async def test_without_the_governed_path_a_deliveries_section_reads_as_before() -> None:
    """No `reads` (a plain test rig): the old path, exactly as the inbox section keeps it."""
    fake = BriefGoogle(events=[], messages=[])
    conn = await connector(fake)
    got = await DeliveriesBrief(PackageScanner(conn)).section(OWNER_UID, UTC, NOW.date())
    assert got.state == "ok" and _gmail(fake)


async def test_the_app_s_deliveries_read_through_the_same_governed_path_as_the_inbox(
    settings: Any,
) -> None:
    from pydantic import SecretStr

    from jarvis.api import create_app
    from jarvis.config import AuthMode
    from jarvis.memory.inmemory import InMemorySessionStore

    s = settings.model_copy(
        update={
            "auth_mode": AuthMode.GOOGLE,
            "google_client_id": "cid.apps.googleusercontent.com",
            "google_client_secret": SecretStr("gsecret"),
            "owner_emails": ["akash@example.com"],
            "session_secret": SecretStr("x" * 32),
            "public_base_url": "http://test",
        }
    )
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        brief = app.state.brief
        deliveries = brief._deliveries  # noqa: SLF001 - the wiring itself is the gate
        assert app.state.google is not None and deliveries is not None
        assert deliveries._reads is not None  # noqa: SLF001
        assert deliveries._reads is brief._collector._reads  # noqa: SLF001
