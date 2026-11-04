# tests/test_r1_wiring_cd.py -- R1 I1 part 2: offline mode (C) and packages / groceries / family /
# mail aloud (D) wired into the real app built by create_app.
from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from telegram_fakes import SECRET, TOKEN, dev_settings

from jarvis.api import create_app
from jarvis.api.app import friendly_llm_error
from jarvis.api.console import APP_ASSETS
from jarvis.api.identity import LEGACY_USER_ID
from jarvis.core import channel
from jarvis.core.channel import telegram_turn
from jarvis.core.guardrails import ActionRisk
from jarvis.llm.base import LLMTransientError, ToolCall
from jarvis.llm.fallback import FallbackFailed
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.offline.rules import OfflineRules
from jarvis.permissions.groups import groups_for
from jarvis.telegram.rules import MARKER, ChannelRules
from jarvis.tools import Tool
from jarvis.tools.gateway import GatewayOutcome
from jarvis.tools.spoken import speaking_now

STATIC = Path(__file__).resolve().parents[1] / "src/jarvis/api/static"
KEY_B64 = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
NEW_ASSETS = (
    "console-offline.js",
    "console-offline.css",
    "console-family.js",
    "console-family.css",
    "console-brief-sections.js",
)
R1, R2, R3 = ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE, ActionRisk.IRREVERSIBLE
R1_TOOLS = {
    "gmail_track_packages": (R1, "email_read"),
    "gmail_unread_digest": (R1, "email_read"),
    "grocery_list": (R1, "groceries"),
    "grocery_add": (R2, "groceries"),
    "grocery_remove": (R2, "groceries"),
    "family_calendar_events": (R1, "family_read"),
    "family_free_slots": (R1, "family_read"),
    "family_event_add": (R3, "family_change"),
}


def _settings(*, telegram: bool = False, google: bool = False, **kw: Any) -> Any:
    extra: dict[str, Any] = {"token_key": SecretStr(KEY_B64)}
    if telegram:
        extra |= {
            "telegram_bot_token": SecretStr(TOKEN),
            "telegram_webhook_secret": SecretStr(SECRET),
        }
    if google:
        from jarvis.config import AuthMode

        extra |= {
            "auth_mode": AuthMode.GOOGLE,
            "google_client_id": "cid.apps.googleusercontent.com",
            "google_client_secret": SecretStr("gsecret"),
            "owner_emails": ["owner@example.com"],
            "session_secret": SecretStr("x" * 32),
            "public_base_url": "http://test",
            "api_token": SecretStr("cli-token"),
        }
    return dev_settings(**extra, **kw)


async def _run(
    s: Any, provider: MockProvider | None = None
) -> AsyncIterator[tuple[Any, AsyncClient]]:
    app = create_app(s, provider=provider or MockProvider(), store=InMemorySessionStore(ttl_s=3600))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            yield app, c


@pytest.fixture
async def plain() -> AsyncIterator[tuple[Any, AsyncClient]]:
    async for x in _run(_settings()):
        yield x


@pytest.fixture
async def both() -> AsyncIterator[tuple[Any, AsyncClient]]:
    async for x in _run(_settings(telegram=True)):
        yield x


@pytest.fixture
async def google() -> AsyncIterator[tuple[Any, AsyncClient]]:
    async for x in _run(_settings(google=True)):
        yield x


@pytest.fixture(autouse=True)
def _fresh() -> None:
    channel.reset_offline()


# ---- offline (C) ---------------------------------------------------------------------------


async def test_the_offline_service_is_built_and_the_route_exists(plain) -> None:
    app, c = plain
    assert app.state.offline is not None
    r = await c.get("/v1/offline")
    assert r.status_code == 200 and r.json()["available"] is True


async def test_without_a_token_key_offline_is_off_but_the_route_answers() -> None:
    async for app, c in _run(dev_settings()):
        assert app.state.offline is None
        r = await c.get("/v1/offline")
        assert r.status_code == 200 and r.json()["available"] is False


async def test_the_brains_share_the_local_fallback(plain) -> None:
    app, _ = plain
    assert app.state.brains.router_for(app.state.brains.default.id) is not None
    assert app.state.offline is not None


async def test_offline_rules_are_the_outermost_layer_without_telegram(plain) -> None:
    app, _ = plain
    assert isinstance(app.state.gateway.rules, OfflineRules)


async def test_offline_rules_are_outermost_with_telegram_and_the_marker_stays_visible(both) -> None:
    app, _ = both
    gw = app.state.gateway
    assert isinstance(gw.rules, OfflineRules)
    assert isinstance(gw.rules._inner, ChannelRules)
    with telegram_turn():
        rules = await gw.rules.rules_for(LEGACY_USER_ID)
    token = app.state.telegram.store.rules_token
    assert any(r.tool_pattern == MARKER and r.reason == token for r in rules)


async def test_an_offline_turn_then_a_calendar_add_comes_back_as_a_card_in_the_real_app(
    plain,
) -> None:
    app, _ = plain
    gw = app.state.gateway
    ran: list[str] = []

    async def add(args: dict[str, Any]) -> dict[str, Any]:
        ran.append("ran")
        return {"ok": True}

    gw.registry.register(
        Tool(
            "calendar_add_event",
            "d",
            {"type": "object", "properties": {}},
            R2,
            add,
            summarize=lambda a: "Add an event",
        )
    )
    call = ToolCall(id="1", name="calendar_add_event", arguments={})
    channel.mark_offline()
    out = (await gw.execute(call, scope="u:s")).outcome
    assert out is GatewayOutcome.AWAITING_CONFIRMATION and ran == []
    channel.reset_offline()
    cloud = (await gw.execute(call.model_copy(update={"id": "2"}), scope="u:s")).outcome
    assert cloud is GatewayOutcome.EXECUTED and ran == ["ran"]


def test_friendly_error_passes_a_fallback_failure_through_in_its_own_words() -> None:
    exc = FallbackFailed("Your laptop could not answer either: it is not reachable.")
    assert friendly_llm_error(exc) == str(exc)
    assert "busy" in friendly_llm_error(LLMTransientError("x"))


# ---- D -------------------------------------------------------------------------------------


async def test_the_family_route_exists_and_is_empty_without_google(plain) -> None:
    app, c = plain
    assert app.state.family is None
    r = await c.get("/v1/family")
    assert r.status_code == 200 and r.json() == {"configured": False}


async def test_with_google_the_family_service_and_the_route_exist(google) -> None:
    app, c = google
    assert app.state.family is not None
    r = await c.get("/v1/family", headers={"Authorization": "Bearer cli-token"})
    assert r.status_code == 200


async def test_the_r1_tools_are_registered_with_their_risks_and_rows(google) -> None:
    app, _ = google
    reg = app.state.gateway.registry
    for name, (risk, row) in R1_TOOLS.items():
        tool = reg.get(name)
        assert tool.risk is risk, name
        assert row in [g.id for g in groups_for(name, tool.risk)], name


async def test_the_brief_has_its_deliveries_and_family_sections(google) -> None:
    app, _ = google
    assert app.state.brief._deliveries is not None
    assert app.state.brief._family_day is not None


async def test_without_google_the_r1_tools_and_brief_sections_are_absent(plain) -> None:
    app, _ = plain
    assert app.state.brief._deliveries is None and app.state.brief._family_day is None
    assert all(app.state.gateway.registry.get(n) is None for n in R1_TOOLS)


@pytest.mark.parametrize("spoken,expect", [(True, True), (False, False)])
async def test_a_voice_turn_in_the_real_app_is_masked_and_a_text_turn_is_not(
    spoken: bool, expect: bool
) -> None:
    prov = MockProvider()
    async for app, c in _run(_settings(), prov):
        seen: list[bool] = []

        async def probe(args: dict[str, Any], seen: list[bool] = seen) -> dict[str, Any]:
            seen.append(speaking_now())
            return {"ok": True}

        app.state.gateway.registry.register(
            Tool("probe_speaking", "d", {"type": "object", "properties": {}}, R1, probe)
        )
        prov.script_tool_calls([ToolCall(id="1", name="probe_speaking", arguments={})], "done")
        body = {"message": "hello", "channel": "voice" if spoken else "text"}
        r = await c.post("/v1/chat", json=body)
        assert r.status_code == 200, r.text
        assert seen == [expect]


async def test_an_unrelated_telegram_turn_is_also_masked(both) -> None:
    app, _ = both
    with telegram_turn():
        assert speaking_now() is True
    assert speaking_now() is False


# ---- console -------------------------------------------------------------------------------


@pytest.mark.parametrize("name", NEW_ASSETS)
async def test_new_console_assets_are_listed_and_served(name: str, plain) -> None:
    _, c = plain
    assert name in APP_ASSETS
    assert (STATIC / name).is_file()
    r = await c.get(f"/static/{name}")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"


async def test_console_html_has_the_tags_in_the_stated_order(plain) -> None:
    _, c = plain
    html = (await c.get("/")).text
    for name in ("console-offline.css", "console-family.css"):
        assert f'<link rel="stylesheet" href="/static/{name}">' in html

    def at(name: str) -> int:
        tag = f'<script src="/static/{name}" defer></script>'
        assert html.count(tag) == 1, name
        return html.index(tag)

    assert at("console-brief-sections.js") < at("console-brief.js")
    assert at("console-family.js") > at("console-drive.js")
    assert at("console-offline.js") > at("console.js")
    assert 'id="vOffline"' in html


def test_console_js_marks_offline_replies() -> None:
    js = (STATIC / "console.js").read_text(encoding="utf-8")
    assert "JarvisOffline.mark(row, r)" in js
