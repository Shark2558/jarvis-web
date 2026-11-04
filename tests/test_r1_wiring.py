# tests/test_r1_wiring.py -- R1 I1: the real app wires Telegram, the Activity observer, the alert
# sink and the new console assets. Built through create_app, not by hand.
from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from telegram_fakes import SECRET, TOKEN, dev_settings

from jarvis.activity.recorder import ActivityRecorder
from jarvis.alerts import NoAlerts
from jarvis.api import create_app
from jarvis.api.console import APP_ASSETS
from jarvis.api.identity import LEGACY_USER_ID
from jarvis.core.channel import telegram_turn
from jarvis.core.guardrails import ConfirmationGate
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.offline.rules import OfflineRules
from jarvis.telegram.alerts import TelegramAlerts
from jarvis.telegram.rules import MARKER, ChannelRules
from jarvis.tools import AuditLog, Gateway, Policy, ToolRegistry
from jarvis.tools.builtin import InMemoryWorld, builtin_tools

STATIC = Path(__file__).resolve().parents[1] / "src/jarvis/api/static"
NEW_ASSETS = (
    "console-telegram.js",
    "console-telegram.css",
    "console-activity.js",
    "console-activity.css",
)


def _gateway() -> Gateway:
    reg = ToolRegistry()
    for t in builtin_tools(InMemoryWorld()):
        reg.register(t)
    return Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())


async def _run(telegram: bool) -> AsyncIterator[tuple[object, AsyncClient]]:
    kw = (
        {"telegram_bot_token": SecretStr(TOKEN), "telegram_webhook_secret": SecretStr(SECRET)}
        if telegram
        else {}
    )
    app = create_app(
        dev_settings(**kw),
        provider=MockProvider(),
        store=InMemorySessionStore(ttl_s=3600),
        gateway=_gateway(),
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            yield app, c


@pytest.fixture
async def with_telegram() -> AsyncIterator[tuple[object, AsyncClient]]:
    async for x in _run(True):
        yield x


@pytest.fixture
async def without_telegram() -> AsyncIterator[tuple[object, AsyncClient]]:
    async for x in _run(False):
        yield x


async def test_with_telegram_the_gateway_rules_carry_the_stores_marker(with_telegram) -> None:
    app, _ = with_telegram
    gw = app.state.gateway
    # R1 I1 part 2: offline mode's rules are outermost, the channel rules sit right inside them
    assert isinstance(gw.rules, OfflineRules) and isinstance(gw.rules._inner, ChannelRules)
    with telegram_turn():
        rules = await gw.rules.rules_for(LEGACY_USER_ID)
    token = app.state.telegram.store.rules_token
    assert any(r.tool_pattern == MARKER and r.reason == token for r in rules)


async def test_with_telegram_private_reads_are_denied_by_default(with_telegram) -> None:
    app, _ = with_telegram
    with telegram_turn():
        rules = await app.state.gateway.rules.rules_for(LEGACY_USER_ID)
    denied = {r.tool_pattern for r in rules if r.source == "telegram" and r.tool_pattern != MARKER}
    assert {"gmail_search", "gmail_read", "drive_*", "contacts_*"} <= denied


async def test_with_telegram_the_alert_sink_is_telegrams_and_the_view_is_served(
    with_telegram,
) -> None:
    app, c = with_telegram
    assert isinstance(app.state.alerts, TelegramAlerts)
    assert app.state.alerts is app.state.telegram.alerts
    assert (await c.get("/v1/telegram")).json()["configured"] is True


async def test_without_telegram_it_is_absent_and_alerts_say_why(without_telegram) -> None:
    app, c = without_telegram
    assert app.state.telegram is None
    assert isinstance(app.state.alerts, NoAlerts)
    assert not isinstance(app.state.gateway.rules._inner, ChannelRules)
    r = await c.post("/telegram/webhook", json={})
    assert r.status_code == 404
    res = await app.state.alerts.send("u", "x", kind="test")
    assert res.sent is False and "Telegram" in (res.reason or "")


async def _check_activity(app, c) -> None:
    mine = [o for o in app.state.gateway.observers if isinstance(o, ActivityRecorder)]
    assert len(mine) == 1
    assert app.state.activity is not None
    r = await c.get("/v1/activity")
    assert r.status_code == 200 and r.json()["available"] is True


async def test_the_activity_observer_is_attached_once_with_telegram(with_telegram) -> None:
    await _check_activity(*with_telegram)


async def test_the_activity_observer_is_attached_once_without_telegram(without_telegram) -> None:
    await _check_activity(*without_telegram)


@pytest.mark.parametrize("name", NEW_ASSETS)
async def test_new_console_assets_are_listed_and_served(name: str, without_telegram) -> None:
    _, c = without_telegram
    assert name in APP_ASSETS
    assert (STATIC / name).is_file()
    r = await c.get(f"/static/{name}")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"


async def test_console_html_has_the_new_tags(without_telegram) -> None:
    _, c = without_telegram
    html = (await c.get("/")).text
    for name in ("console-telegram.css", "console-activity.css"):
        assert f'<link rel="stylesheet" href="/static/{name}">' in html
    for name in ("console-telegram.js", "console-activity.js"):
        assert f'<script src="/static/{name}" defer></script>' in html


async def test_the_scheduler_tick_sweeps_telegram_and_activity() -> None:
    from test_scheduler_auth import KEY, SA, FakeJWKS, token, verifier

    from jarvis.api.scheduler_auth import TICK_PATH
    from jarvis.config import SessionBackend

    s = dev_settings(
        brief_scheduler_sa=SA,
        public_base_url="http://test",
        session_backend=SessionBackend.FIRESTORE,  # the tick route needs persistent storage
        telegram_bot_token=SecretStr(TOKEN),
        telegram_webhook_secret=SecretStr(SECRET),
    )
    app = create_app(
        s,
        provider=MockProvider(),
        store=InMemorySessionStore(),
        scheduler_verifier=verifier(FakeJWKS(KEY)),
    )
    async with app.router.lifespan_context(app):
        ran: list[str] = []

        async def tg() -> int:
            ran.append("telegram")
            return 0

        async def act(owners: object) -> int:
            ran.append("activity")
            raise RuntimeError("a failing sweep must not fail the tick")

        app.state.telegram.store.sweep = tg
        app.state.activity.sweep = act
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(TICK_PATH, headers={"Authorization": f"Bearer {token()}"})
    assert r.status_code == 200 and ran == ["telegram", "activity"]
