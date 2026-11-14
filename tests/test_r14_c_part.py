# tests/test_r14_c_part.py -- R14 Part C's one join (`jarvis.skills.part.build`, contract
# `jarvis.hardening.ports`): the tool `skills_open`, the services `offer` (only while tool_offer
# is "by_skill") and `ledger` (only while token_ledger_enabled), the Vitals item `ai_parts`, the
# `token_ledger` privacy row; then through the real app: the brain's two slots narrow the tools
# a model call is offered and count every call, and GET /v1/skills, GET /v1/costs/ledger answer.
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from r14_fakes_c import UID

from jarvis.api import create_app
from jarvis.api.r14_wiring import check_part
from jarvis.billing.ledger import TokenLedgerStore
from jarvis.config import Settings
from jarvis.hardening.ports import HardeningContext
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.skills import part as skills_part
from jarvis.skills.ids import SKILL_IDS
from jarvis.skills.offer import SkillOffer
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog

KOLKATA = ZoneInfo("Asia/Kolkata")


def _ctx(s: Settings, docs: MemoryDocs | None, state: dict[str, Any] | None = None) -> Any:
    got = state or {}
    return HardeningContext(s=s, docs=docs, audit=AuditLog(), state=got.get)


def test_the_part_builds_its_tool_services_vitals_and_privacy_row(settings: Settings) -> None:
    part = check_part("skills", skills_part.build(_ctx(settings, MemoryDocs())))
    assert part.ready == skills_part.READY
    assert [t.name for t in part.tools] == ["skills_open"]
    assert isinstance(part.services["offer"], SkillOffer)
    assert isinstance(part.services["ledger"], TokenLedgerStore)
    assert len(part.vitals) == 1 and [p.id for p in part.privacy] == ["token_ledger"]
    assert not part.clock_jobs and not part.daily_jobs


def test_the_kill_switch_and_the_ledger_switch_leave_their_service_out(
    settings: Settings,
) -> None:
    off = settings.model_copy(update={"tool_offer": "all", "token_ledger_enabled": False})
    part = check_part("skills", skills_part.build(_ctx(off, MemoryDocs())))
    assert "offer" not in part.services and "ledger" not in part.services
    assert [t.name for t in part.tools] == ["skills_open"]  # opening a skill still answers
    assert "every tool" in part.ready and "switched off" in part.ready


def test_without_a_document_store_there_is_no_ledger(settings: Settings) -> None:
    part = check_part("skills", skills_part.build(_ctx(settings, None)))
    assert "ledger" not in part.services and "offer" in part.services
    assert not part.privacy and "document store" in part.ready


def test_a_catalogue_that_cannot_be_read_fails_the_part_so_every_tool_is_offered(
    settings: Settings, monkeypatch: Any
) -> None:
    from jarvis.api import r14_wiring

    def broken() -> Any:
        raise skills_part.CatalogueError("catalogue unreadable: OSError")

    monkeypatch.setattr(skills_part, "load_catalogue", broken)
    parts = r14_wiring.build_parts(_ctx(settings, MemoryDocs()))
    assert parts["skills"].ready == r14_wiring.SETUP_FAILED and not parts["skills"].services


async def test_the_vitals_item_says_where_the_money_goes_in_rupees(settings: Settings) -> None:
    docs = MemoryDocs()
    part = skills_part.build(_ctx(settings, docs))
    now = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)
    (item,) = await part.vitals[0](UID, now, KOLKATA)
    assert item.provider.id == "ai_parts" and item.base[0] == "ok"
    assert item.provider.note.startswith("No AI calls")
    off = settings.model_copy(update={"token_ledger_enabled": False})
    (quiet,) = await skills_part.build(_ctx(off, docs)).vitals[0](UID, now, KOLKATA)
    assert quiet.base[0] == "unknown" and "off" in quiet.provider.note


async def test_the_privacy_row_counts_days_and_offers_no_export_or_delete(
    settings: Settings,
) -> None:
    part = skills_part.build(_ctx(settings, MemoryDocs()))
    view = await part.privacy[0].describe(UID)
    assert view.id == "token_ledger" and view.count == 0
    assert view.export is False and view.delete == "none" and "90 days" in view.retention


@asynccontextmanager
async def _app(s: Settings, provider: MockProvider) -> AsyncIterator[tuple[FastAPI, AsyncClient]]:
    app = create_app(s, provider=provider, store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield app, c


async def test_through_the_app_the_offer_narrows_and_the_ledger_counts(
    settings: Settings,
) -> None:
    provider = MockProvider()
    async with _app(settings, provider) as (app, client):
        assert app.state.r14_parts["skills"].ready == skills_part.READY
        assert isinstance(app.state.brain.slots.offer, SkillOffer)
        every = len(app.state.gateway.registry)
        r = await client.post("/v1/chat", json={"message": "what's the weather like?"})
        assert r.status_code == 200, r.text
        offered = [t.name for t in provider.calls[-1].tools or []]
        assert "skills_open" in offered and len(offered) < every
        skills = (await client.get("/v1/skills")).json()
        assert [x["id"] for x in skills["skills"]] == list(SKILL_IDS)
        assert skills["ready"] == skills_part.READY and skills["tool_offer"] == "by_skill"
        assert skills["tools"] == every
        costs = await client.get("/v1/costs/ledger")
        body = costs.json()
        assert costs.headers["cache-control"] == "no-store"
        assert body["enabled"] is True and body["calls"] >= 1
        assert set(body["inr"]) >= {"persona", "tools", "replies"}
        assert "what's the weather" not in costs.text


async def test_with_all_tools_the_brain_offers_every_tool(settings: Settings) -> None:
    provider = MockProvider()
    s = settings.model_copy(update={"tool_offer": "all"})
    async with _app(s, provider) as (app, client):
        assert app.state.brain.slots.offer is None
        await client.post("/v1/chat", json={"message": "what's the weather like?"})
        assert len(provider.calls[-1].tools or []) == len(app.state.gateway.registry)


async def test_the_routes_need_the_owner(settings: Settings) -> None:
    s = settings.model_copy(update={"env": "prod", "api_token": SecretStr("t" * 32)})
    async with _app(s, MockProvider()) as (_, client):
        for route in ("/v1/skills", "/v1/costs/ledger"):
            assert (await client.get(route)).status_code == 401, route


async def test_the_privacy_dashboard_lists_the_ledger_row(settings: Settings) -> None:
    async with _app(settings, MockProvider()) as (_, client):
        body = (await client.get("/v1/privacy")).json()
        row = next(x for x in body["categories"] if x["id"] == "token_ledger")
        assert row["delete"] == "none" and row["export"] is False and row["count"] == 0


async def test_a_tool_the_offer_left_out_still_meets_every_gateway_check(
    settings: Settings,
) -> None:
    from jarvis.llm.base import ToolCall

    provider = MockProvider()
    args = {"bill": "rent", "upi": "landlord@okhdfcbank"}
    call = ToolCall(id="c1", name="bill_payee_set", arguments=args)
    provider.script_tool_calls([call], "Noted, Sir.")
    async with _app(settings, provider) as (app, client):
        r = await client.post("/v1/chat", json={"message": "what's the weather like?"})
        assert r.status_code == 200, r.text
        assert "bill_payee_set" not in [t.name for t in provider.calls[0].tools or []]
        tail = await app.state.gateway.audit.tail(20)
        mine = [e for e in tail.entries if e.tool == "bill_payee_set"]
        assert mine and "executed" not in {e.outcome for e in mine}  # audited, refused or a card
        second = [t.name for t in provider.calls[1].tools or []]
        assert "bill_payee_set" in second  # the replayed call names it: the provider knows it
