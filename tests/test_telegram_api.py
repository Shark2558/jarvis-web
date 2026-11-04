# tests/test_telegram_api.py -- R1 D2/D6: the console's Telegram routes (owner only).
# GET /v1/telegram,
# POST/DELETE /v1/telegram/pair, PUT /v1/telegram/settings, POST /v1/telegram/test-alert. Errors are
# {error, detail}; nothing from Telegram's own error text reaches the owner.
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from telegram_fakes import (
    OWNER_CHAT,
    OWNER_TG,
    SECRET,
    TOKEN,
    World,
    build_world,
    dev_settings,
    message,
)

from jarvis.api import create_app
from jarvis.api.telegram import build_telegram, install_telegram
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage.docs import MemoryDocs
from jarvis.tools import AuditLog


@pytest.fixture
async def api() -> AsyncIterator[tuple[AsyncClient, World]]:
    w = build_world()
    s = dev_settings(telegram_bot_token=SecretStr(TOKEN), telegram_webhook_secret=SecretStr(SECRET))
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore(), gateway=w.gateway)
    install_telegram(app)
    async with app.router.lifespan_context(app):
        app.state.telegram = w.service
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c, w


async def test_build_telegram_is_off_without_both_secrets() -> None:
    docs, audit = MemoryDocs(), AuditLog()
    assert build_telegram(dev_settings(), docs, audit=audit) is None
    only_token = dev_settings(telegram_bot_token=SecretStr(TOKEN))
    assert build_telegram(only_token, docs, audit=audit) is None
    only_secret = dev_settings(telegram_webhook_secret=SecretStr(SECRET))
    assert build_telegram(only_secret, docs, audit=audit) is None
    both = dev_settings(
        telegram_bot_token=SecretStr(TOKEN), telegram_webhook_secret=SecretStr(SECRET)
    )
    svc = build_telegram(both, docs, audit=audit)
    assert svc is not None and svc.alerts is not None and svc.store is not None


async def test_off_server_view_says_not_configured() -> None:
    app = create_app(dev_settings(), provider=MockProvider(), store=InMemorySessionStore())
    install_telegram(app)
    async with app.router.lifespan_context(app):
        app.state.telegram = None
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            assert (await c.get("/v1/telegram")).json() == {"configured": False}
            r = await c.post("/v1/telegram/pair")
            assert r.status_code == 404 and r.json()["error"] == "telegram_off"
            assert (await c.post("/v1/telegram/test-alert")).json()["sent"] is False


async def test_view_before_pairing(api: tuple[AsyncClient, World]) -> None:
    c, w = api
    v = (await c.get("/v1/telegram")).json()
    assert v["configured"] is True and v["bot_username"] == "jarvis_test_bot"
    assert v["paired"] is False and v["account_hint"] is None
    assert v["pairing_pending"] is False
    assert v["webhook"] == {"registered": True, "pending": 0, "last_error": None}
    assert v["allow_private_reads"] is False
    assert v["alerts"] == {"approval_waiting": True, "offline": True, "brief_ready": False}
    assert TOKEN not in str(v) and SECRET not in str(v)


async def test_pair_gives_a_code_and_a_deep_link_and_finishes_in_telegram(
    api: tuple[AsyncClient, World],
) -> None:
    c, w = api
    r = await c.post("/v1/telegram/pair")
    assert r.status_code == 200
    body = r.json()
    assert len(body["code"]) == 8 and body["expires_in_s"] == 600
    assert body["link"] == f"https://t.me/jarvis_test_bot?start={body['code']}"
    assert (await c.get("/v1/telegram")).json()["pairing_pending"] is True
    await w.send(message(1, f"/start {body['code']}"))
    v = (await c.get("/v1/telegram")).json()
    assert v["paired"] is True and v["account_hint"] == f"••{str(OWNER_TG)[-4:]}"
    assert v["paired_at"]
    assert str(OWNER_TG) not in str(v) and str(OWNER_CHAT) not in str(v)
    assert len(w.audited("telegram_pair_start")) == 1


async def test_pairing_again_while_paired_is_a_409(api: tuple[AsyncClient, World]) -> None:
    c, w = api
    await w.pair()
    r = await c.post("/v1/telegram/pair")
    assert r.status_code == 409 and r.json()["error"] == "already_paired"


async def test_pair_when_telegram_is_unreachable_is_a_plain_503(
    api: tuple[AsyncClient, World],
) -> None:
    c, w = api
    w.bot.raise_transport = True
    r = await c.post("/v1/telegram/pair")
    assert r.status_code == 503 and r.json()["error"] == "telegram_unavailable"
    assert TOKEN not in r.text and "boom" not in r.text


async def test_unpair_is_audited(api: tuple[AsyncClient, World]) -> None:
    c, w = api
    await w.pair()
    r = await c.delete("/v1/telegram/pair")
    assert r.status_code == 200 and r.json()["paired"] is False
    assert await w.store.get("owner") is None
    assert len(w.audited("telegram_unpair")) == 1
    assert (await c.delete("/v1/telegram/pair")).status_code == 200  # idempotent


async def test_settings_need_pairing_and_are_strict(api: tuple[AsyncClient, World]) -> None:
    c, w = api
    r = await c.put("/v1/telegram/settings", json={"allow_private_reads": True})
    assert r.status_code == 409 and r.json()["error"] == "not_paired"
    await w.pair()
    assert (
        await c.put("/v1/telegram/settings", json={"allow_private_reads": "yes"})
    ).status_code == 422
    assert (await c.put("/v1/telegram/settings", json={"surprise": 1})).status_code == 422
    assert (
        await c.put("/v1/telegram/settings", json={"alerts": {"nope": True}})
    ).status_code == 422


async def test_settings_change_and_audit(api: tuple[AsyncClient, World]) -> None:
    c, w = api
    await w.pair()
    r = await c.put(
        "/v1/telegram/settings",
        json={"allow_private_reads": True, "alerts": {"brief_ready": True, "offline": False}},
    )
    assert r.status_code == 200
    v = r.json()
    assert v["allow_private_reads"] is True
    assert v["alerts"] == {"approval_waiting": True, "offline": False, "brief_ready": True}
    assert len(w.audited("telegram_settings")) == 1
    link = await w.store.get("owner")
    assert link is not None and link.allow_private_reads is True


async def test_test_alert(api: tuple[AsyncClient, World]) -> None:
    c, w = api
    r = await c.post("/v1/telegram/test-alert")
    assert r.json()["sent"] is False and r.json()["reason"]
    await w.pair()
    r = await c.post("/v1/telegram/test-alert")
    assert r.json() == {"sent": True}
    assert len(w.bot.texts) == 1


async def test_test_alert_is_rate_limited_by_the_alert_caps(api: tuple[AsyncClient, World]) -> None:
    c, w = api
    await w.pair()
    sent = 0
    for _ in range(14):
        r = await c.post("/v1/telegram/test-alert")
        sent += bool(r.json()["sent"])
    assert sent == 10


async def test_pair_endpoint_is_throttled(api: tuple[AsyncClient, World]) -> None:
    c, w = api
    codes: list[Any] = []
    for _ in range(30):
        r = await c.post("/v1/telegram/pair")
        codes.append(r.status_code)
    assert 429 in codes


async def test_signed_out_callers_are_refused() -> None:
    s = dev_settings(
        telegram_bot_token=SecretStr(TOKEN),
        telegram_webhook_secret=SecretStr(SECRET),
        api_token=SecretStr("cli-token"),
    )
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    install_telegram(app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            for method, path in [
                ("GET", "/v1/telegram"),
                ("POST", "/v1/telegram/pair"),
                ("DELETE", "/v1/telegram/pair"),
                ("PUT", "/v1/telegram/settings"),
                ("POST", "/v1/telegram/test-alert"),
            ]:
                assert (await c.request(method, path)).status_code == 401
