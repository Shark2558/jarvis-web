# tests/test_home_api.py -- R3 D3-D6 over HTTP: /home/link, /internal/home/watchdog, /v1/home*.
from __future__ import annotations

import base64
import zipfile
from collections.abc import AsyncIterator
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import pytest
from home_fakes import URL, World, build
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.api import create_app
from jarvis.api.home import install_home
from jarvis.api.identity import user_id_for_email
from jarvis.config import AuthMode, Settings
from jarvis.home import kit, signing
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore

OWNER = "akash@example.com"
UID = user_id_for_email(OWNER)
CSRF = {"X-Requested-With": "JARVIS"}


@pytest.fixture
def gsettings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "auth_mode": AuthMode.GOOGLE,
            "google_client_id": "cid.apps.googleusercontent.com",
            "google_client_secret": SecretStr("gsecret"),
            "owner_emails": [OWNER],
            "session_secret": SecretStr("x" * 32),
            "public_base_url": "https://jarvis.test",
            "api_token": SecretStr("cli-token"),
        }
    )


@pytest.fixture
async def w(tmp_path: Path):
    world = build(tmp_path)
    yield world
    await world.aclose()


async def owner_client(
    gsettings: Settings, w: World, *, home_on: bool = True
) -> AsyncIterator[AsyncClient]:
    app = create_app(gsettings, provider=MockProvider(), store=InMemorySessionStore())
    install_home(app)
    async with app.router.lifespan_context(app):
        if home_on:
            app.state.home_store = w.store
            app.state.home_link = w.link
            app.state.home_devices = w.devices
            app.state.home_webhook = w.webhook
            app.state.home_watchdog = w.watchdog

        async def fake(request: Any) -> dict[str, Any]:
            return {"userinfo": {"email": OWNER, "email_verified": True, "sub": OWNER}}

        app.state.oauth.google.authorize_access_token = fake
        c = AsyncClient(transport=ASGITransport(app=app), base_url="https://jarvis.test")
        assert (await c.get("/auth/callback?code=abc&state=x")).status_code in (302, 307)
        yield c
        await c.aclose()


@pytest.fixture
async def gc(gsettings: Settings, w: World):
    async for c in owner_client(gsettings, w):
        yield c


async def link_via_owner_code(gc: AsyncClient, w: World) -> str:
    code = (await gc.post("/v1/home/link-code", headers=CSRF)).json()["code"]
    return await w.bridge.link.link(code, URL, bytes(range(1, 33)))


async def test_needs_sign_in_and_csrf(gsettings: Settings, w: World) -> None:
    async for c in owner_client(gsettings, w):
        assert (await c.get("/v1/home")).status_code == 200
        assert (await c.post("/v1/home/link-code")).status_code == 403  # no CSRF header
        assert (await c.put("/v1/home/devices", json={"entities": []})).status_code == 403
        bare = AsyncClient(transport=c._transport, base_url="https://jarvis.test")
        for method, path in (
            ("get", "/v1/home"),
            ("get", "/v1/home/kit"),
            ("get", "/v1/home/devices"),
        ):
            assert (await getattr(bare, method)(path)).status_code == 401
        await bare.aclose()


async def test_off_without_a_key(gsettings: Settings, w: World) -> None:
    async for c in owner_client(gsettings, w, home_on=False):
        body = (await c.get("/v1/home")).json()
        assert body["available"] is False and "no encryption key" in body["reason"]
        r = await c.post("/v1/home/link-code", headers=CSRF)
        assert r.status_code == 503 and r.json()["error"] == "unavailable"
        assert (await c.post("/home/webhook", content=b"{}")).status_code == 404
        assert (
            await c.post(
                "/home/link",
                json={
                    "code": "x",
                    "bridge_url": URL,
                    "bridge_version": "0.1.0",
                    "link_secret": "a" * 43,
                },
            )
        ).status_code == 404


async def test_link_then_status_then_unlink(gc: AsyncClient, w: World) -> None:
    first = (await gc.get("/v1/home")).json()
    assert first["linked"] is False and first["state"] == "not_linked"
    code = (await gc.post("/v1/home/link-code", headers=CSRF)).json()
    assert len(code["code"]) == 9 and code["expires_in_s"] == 600
    await w.bridge.link.link(code["code"], URL, bytes(range(1, 33)))
    await w.bridge.heartbeat.beat()  # type: ignore[union-attr]
    body = (await gc.get("/v1/home")).json()
    assert body["linked"] and body["state"] == "online" and body["host"] == "laptop.tail1234.ts.net"
    # R11.1 C: the real bridge reports the kit's own version (0.2.0: the first with photo routes)
    assert body["parts"]["ha"] is True and body["bridge_version"] == "0.2.0"
    assert body["kit_outdated"] is False and body["devices_available"] is True
    assert "seed" not in str(body) and "tail1234.ts.net:8443" not in str(body)
    w.clock.t += 800
    assert (await gc.get("/v1/home")).json()["state"] == "offline"
    r = await gc.delete("/v1/home/link", headers=CSRF)
    assert r.status_code == 422 and r.json()["error"] == "confirm_required"
    assert (await gc.get("/v1/home")).json()["linked"] is True
    r = await gc.delete("/v1/home/link?confirm=1", headers=CSRF)
    assert r.status_code == 200 and r.json() == {"unlinked": True}
    assert (await gc.get("/v1/home")).json()["linked"] is False


async def test_link_route_answers(w: World) -> None:
    code = (await w.link.code(next(iter([UID])))).code
    body = {"code": code, "bridge_url": URL, "bridge_version": "0.1.0", "link_secret": "a" * 43}
    bad = await w.cloud.post("/home/link", json={**body, "code": "ZZZZ-ZZZZ"})
    assert bad.status_code == 401 and bad.content == b""
    r = await w.cloud.post("/home/link", json={**body, "bridge_url": "http://x.ts.net"})
    assert r.status_code == 422 and r.json()["error"] == "bad_url" and r.json()["detail"]
    r = await w.cloud.post("/home/link", json=body)  # nothing at the address answers with the key
    assert r.status_code == 409 and r.json()["error"] == "not_reachable"
    extra = await w.cloud.post("/home/link", json={**body, "evil": 1})
    assert extra.status_code == 422


async def test_link_route_returns_the_seed_once_and_rate_limits(w: World) -> None:
    secret = base64.urlsafe_b64encode(b"k" * 32).decode().rstrip("=")
    w.bridge.store.set_pending(b"k" * 32)
    code = (await w.link.code(UID)).code
    r = await w.cloud.post(
        "/home/link",
        json={"code": code, "bridge_url": URL, "bridge_version": "0.1.0", "link_secret": secret},
    )
    assert r.status_code == 201 and r.headers["cache-control"] == "no-store"
    seed = base64.urlsafe_b64decode(r.json()["seed"] + "=")
    rec = await w.store.load(UID)
    assert rec is not None and rec.seed == seed and rec.home_id == r.json()["home_id"]
    again = await w.cloud.post(
        "/home/link",
        json={"code": code, "bridge_url": URL, "bridge_version": "0.1.0", "link_secret": secret},
    )
    assert again.status_code == 401  # spent
    codes = [
        (
            await w.cloud.post(
                "/home/link",
                json={
                    "code": "ZZZZ-ZZZZ",
                    "bridge_url": URL,
                    "bridge_version": "0.1.0",
                    "link_secret": secret,
                },
            )
        ).status_code
        for _ in range(12)
    ]
    assert 429 in codes


async def test_kit_download(gc: AsyncClient) -> None:
    r = await gc.get("/v1/home/kit")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-kit-sha256"] == kit.sha256(r.content)
    zf = zipfile.ZipFile(BytesIO(r.content))
    assert b"JARVIS_URL=https://jarvis.test" in zf.read("JARVIS-Home/bridge.env")
    info = (await gc.get("/v1/home/kit/info")).json()
    assert info["sha256"] == r.headers["x-kit-sha256"] and info["version"] == kit.KIT_VERSION


async def test_kit_needs_a_public_address(gsettings: Settings, w: World) -> None:
    async for c in owner_client(
        gsettings.model_copy(update={"public_base_url": "http://jarvis.test"}), w
    ):
        r = await c.get("/v1/home/kit")
        assert r.status_code == 503 and r.json()["error"] == "kit_unavailable"


async def test_devices_endpoints(gc: AsyncClient, w: World) -> None:
    await link_via_owner_code(gc, w)
    cat = (await gc.get("/v1/home/devices?catalogue=1")).json()["devices"]
    ids = {d["entity_id"] for d in cat}
    assert "lock.gate" in ids and "script.goodnight" not in ids
    lock = next(d for d in cat if d["entity_id"] == "lock.gate")
    assert lock["classes"] == ["always_passkey"]
    bad = await gc.put(
        "/v1/home/devices", headers=CSRF,
        json={"entities": [{"entity_id": "lock.gate", "class": "everyday"}]},
    )  # fmt: skip
    assert bad.status_code == 422 and bad.json()["error"] == "class_not_allowed"
    ok = await gc.put(
        "/v1/home/devices", headers=CSRF,
        json={"entities": [{"entity_id": "light.torch", "label": "Torch", "class": "everyday"}]},
    )  # fmt: skip
    assert ok.status_code == 200 and ok.json()["count"] == 1
    got = (await gc.get("/v1/home/devices")).json()
    assert got["entities"][0]["label"] == "Torch" and got["entities"][0]["class"] == "everyday"
    too_many = await gc.put(
        "/v1/home/devices",
        headers=CSRF,
        json={"entities": [{"entity_id": "light.a", "class": "x"}] * 51},
    )
    assert too_many.status_code == 422
    extra = await gc.put("/v1/home/devices", headers=CSRF, json={"entities": [], "x": 1})
    assert extra.status_code == 422


async def test_laptop_off_is_a_plain_409(gc: AsyncClient, w: World) -> None:
    await link_via_owner_code(gc, w)
    w.client._inner = httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("x")))  # noqa: SLF001
    r = await gc.get("/v1/home/devices?catalogue=1")
    assert r.status_code == 409 and r.json()["error"] == "laptop_off"
    assert "off, asleep or offline" in r.json()["detail"]


async def test_unreadable_record_is_503(gc: AsyncClient, w: World) -> None:
    await link_via_owner_code(gc, w)
    w.docs._data[f"jarvis_home/{UID}"]["blob"] = "x"  # noqa: SLF001
    r = await gc.get("/v1/home")
    assert r.status_code == 503 and r.json()["error"] == "unavailable"


async def test_watchdog_needs_the_scheduler(gc: AsyncClient, w: World) -> None:
    r = await gc.post("/internal/home/watchdog")
    assert r.status_code in (401, 403)
    assert r.content != b"" or r.status_code == 401
    out = await w.watchdog.run()
    assert set(out) >= {"homes", "offline", "held_sent", "swept", "jobs"}
    assert out["jobs"] == {"home_offline": "ok", "home_claims_sweep": "ok", "home_link_sweep": "ok"}


async def test_webhook_via_the_real_app_routes(gc: AsyncClient, w: World) -> None:
    await link_via_owner_code(gc, w)
    rec = await w.store.load(UID)
    assert rec is not None
    body = b'{"id":"hb-9","type":"heartbeat","at":1.0,"bridge_version":"0.1.0","state_rev":0}'
    h = signing.sign(
        rec.keys(),
        "up",
        home_id=rec.home_id,
        method="POST",
        target="/home/webhook",
        body=body,
        now=w.clock(),
    )
    r = await gc.post("/home/webhook", content=body, headers={signing.HEADER: h})
    assert r.status_code == 200 and signing.HEADER in r.headers
    assert (await gc.post("/home/webhook", content=body)).status_code == 401
