# tests/test_offline_api.py -- R1 C: /v1/offline over HTTP. Owner-only (require_auth), cookie writes
# need X-Requested-With, plain-words errors {error, detail}, rate-limited, audited by hash only,
# and the key / full URL never in a response.
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from offline_fakes import KEY, MODEL, URL, Rig
from pydantic import SecretStr

from jarvis.api import create_app
from jarvis.api.offline import CHANGES_PER_MINUTE
from jarvis.config import AuthMode, Settings
from jarvis.core.guardrails import ConfirmationGate
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.tools import AuditLog, Gateway, Policy, ToolRegistry


@pytest.fixture
def secured(settings: Settings) -> Settings:
    return settings.model_copy(
        update={"api_token": SecretStr("tok-123"), "auth_mode": AuthMode.TOKEN}
    )


async def _client(settings: Settings, rig: Rig | None) -> AsyncIterator[tuple[AsyncClient, Any]]:
    gw = Gateway(
        registry=ToolRegistry(), policy=Policy(), gate=ConfirmationGate(), audit=AuditLog()
    )
    app = create_app(
        settings, provider=MockProvider(), store=InMemorySessionStore(ttl_s=3600), gateway=gw
    )
    async with app.router.lifespan_context(app):
        # the real app builds its own service in the lifespan (R1 I1); the test's replaces it
        app.state.offline = rig.svc if rig else None
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c, app


@pytest.fixture
async def on(settings: Settings) -> AsyncIterator[tuple[AsyncClient, Any, Rig]]:
    rig = await Rig(configured=False).ready()
    async for c, app in _client(settings, rig):
        yield c, app, rig


@pytest.fixture
async def off(settings: Settings) -> AsyncIterator[AsyncClient]:
    async for c, _ in _client(settings, None):
        yield c


async def test_get_without_the_feature_says_not_available(off: AsyncClient) -> None:
    r = await off.get("/v1/offline")
    assert r.status_code == 200
    j = r.json()
    assert j["available"] is False and j["configured"] is False and j["state"] == "off"


async def test_writes_without_the_feature_say_why(off: AsyncClient) -> None:
    for call in (
        off.put("/v1/offline", json={"enabled": True}),
        off.delete("/v1/offline"),
        off.post("/v1/offline/test"),
    ):
        r = await call
        assert r.status_code == 404 and r.json()["error"] == "offline_off"
        assert "token key" in r.json()["detail"]


async def test_the_whole_flow(on: tuple[AsyncClient, Any, Rig]) -> None:
    c, _, rig = on
    g = (await c.get("/v1/offline")).json()
    assert g["available"] is True and g["configured"] is False and g["state"] == "off"

    r = await c.put("/v1/offline", json={"url": URL, "key": KEY, "model": MODEL})
    assert r.status_code == 200
    j = r.json()
    assert j["configured"] is True and j["enabled"] is False and j["host"].endswith(".ts.net")
    assert KEY not in r.text and "https://" not in r.text

    t = (await c.post("/v1/offline/test")).json()
    assert t["ok"] is True and "answered" in t["detail"] and t["models"] == [MODEL]

    j = (await c.put("/v1/offline", json={"enabled": True})).json()
    assert j["enabled"] is True and j["state"] == "standby"

    j = (await c.delete("/v1/offline")).json()
    assert j["configured"] is False and await rig.store.get() is None


async def test_bad_input_is_plain_words_and_never_echoes_the_key(
    on: tuple[AsyncClient, Any, Rig],
) -> None:
    c, _, _ = on
    r = await c.put(
        "/v1/offline", json={"url": "http://192.168.1.5:11434", "key": KEY, "model": MODEL}
    )
    assert r.status_code == 422 and r.json()["error"] == "invalid_url"
    assert "https" in r.json()["detail"] and KEY not in r.text
    r = await c.put("/v1/offline", json={"url": URL, "key": "short", "model": MODEL})
    assert r.status_code == 422 and r.json()["error"] == "invalid_key"
    r = await c.put("/v1/offline", json={"enabled": True})
    assert r.status_code == 422 and r.json()["error"] == "missing"


@pytest.mark.parametrize(
    "body",
    [
        {"enabled": "yes"},
        {"enabled": 1},
        {"url": 5},
        {"key": ["a"]},
        {"model": {"x": 1}},
        {"extra": 1},
        {"url": "x" * 5000},
        {"key": "k" * 5000},
    ],
)
async def test_wrong_types_and_oversized_fields_are_422(
    on: tuple[AsyncClient, Any, Rig], body: dict[str, Any]
) -> None:
    c, _, rig = on
    r = await c.put("/v1/offline", json=body)
    assert r.status_code == 422
    assert await rig.store.get() is None


async def test_changes_are_rate_limited(on: tuple[AsyncClient, Any, Rig]) -> None:
    c, _, _ = on
    codes = [
        (await c.put("/v1/offline", json={"model": "x"})).status_code
        for _ in range(CHANGES_PER_MINUTE + 3)
    ]
    assert 429 in codes


async def test_a_change_is_audited_by_hash_only(on: tuple[AsyncClient, Any, Rig]) -> None:
    c, app, _ = on
    await c.put("/v1/offline", json={"url": URL, "key": KEY, "model": MODEL})
    tail = await app.state.gateway.audit.tail(50)
    entries = [e for e in tail.entries if e.agent == "offline"]
    assert entries and entries[-1].outcome == "changed"
    assert KEY not in json.dumps(entries[-1].model_dump(), default=str)
    assert "ts.net" not in json.dumps(entries[-1].model_dump(), default=str)


async def test_requires_the_owner(secured: Settings) -> None:
    rig = await Rig(configured=False).ready()
    async for c, _ in _client(secured, rig):
        assert (await c.get("/v1/offline")).status_code == 401
        assert (await c.put("/v1/offline", json={"enabled": True})).status_code == 401
        assert (await c.post("/v1/offline/test")).status_code == 401
        ok = await c.get("/v1/offline", headers={"Authorization": "Bearer tok-123"})
        assert ok.status_code == 200
