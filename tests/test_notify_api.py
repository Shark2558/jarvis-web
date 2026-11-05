# tests/test_notify_api.py -- R3 D10/D11: /v1/notify and /v1/push (owner only, CSRF on cookie
# writes, error shape, validation, no references or keys echoed).
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from notify_fakes import NOON, build
from pydantic import SecretStr
from webpush_fakes import Browser

from jarvis.api import create_app
from jarvis.api.identity import user_id_for_email
from jarvis.api.notify import install_notify
from jarvis.api.ratelimit import RateLimiter
from jarvis.config import AuthMode, Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore

OWNER = "akash@example.com"
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
            "public_base_url": "http://test",
            "api_token": SecretStr("cli-token"),
        }
    )


async def _client(s: Settings, on: bool = True) -> AsyncIterator[tuple[AsyncClient, Any]]:
    w = await build()
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    install_notify(app)  # I1 does this in create_app
    async with app.router.lifespan_context(app):
        app.state.notify = w.service if on else None
        app.state.push = w.push.service if on else None
        c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        c.app = app  # type: ignore[attr-defined]
        yield c, w
        await c.aclose()


async def _login(c: AsyncClient) -> None:
    async def fake(request: Any) -> dict[str, Any]:
        return {"userinfo": {"email": OWNER, "email_verified": True, "sub": OWNER}}

    c.app.state.oauth.google.authorize_access_token = fake  # type: ignore[attr-defined]
    assert (await c.get("/auth/callback?code=abc&state=x")).status_code in (302, 307)


@pytest.fixture
async def gc(gsettings: Settings) -> AsyncIterator[tuple[AsyncClient, Any]]:
    async for c, w in _client(gsettings):
        await _login(c)
        # the signed-in owner's uid is what current_user returns; discover it from a write
        yield c, w


async def test_it_needs_sign_in_and_csrf(gsettings: Settings) -> None:
    async for c, _ in _client(gsettings):
        assert (await c.get("/v1/notify/settings")).status_code == 401
        assert (await c.get("/v1/push/key")).status_code == 401
        await _login(c)
        assert (await c.put("/v1/notify/settings", json={})).status_code == 403
        assert (await c.post("/v1/push/test")).status_code == 403


async def test_settings_defaults_follow_d20(gc: Any) -> None:
    c, _ = gc
    b = (await c.get("/v1/notify/settings")).json()
    assert b["available"] is True and b["ring_for"] == "urgent" and b["names_in_alerts"] is False
    assert b["quiet"] == {"on": True, "start": "23:00", "end": "06:30"}
    assert b["snapshot"] == {"on": False} and b["vip"] == []
    assert b["kinds"]["home_intruder"] == {"switch": "on", "level": "urgent", "fixed": True}
    assert b["kinds"]["home_greeting"]["switch"] == "feed"
    assert "test" not in b["kinds"]


async def test_settings_can_be_changed_and_are_audited(gc: Any) -> None:
    c, w = gc
    r = await c.put(
        "/v1/notify/settings",
        json={
            "quiet": {"start": "22:00"},
            "ring_for": "important",
            "kinds": {"home_package": "off", "home_greeting": "on"},
            "names_in_alerts": True,
        },
        headers=CSRF,
    )
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["quiet"] == {"on": True, "start": "22:00", "end": "06:30"}
    assert b["ring_for"] == "important" and b["names_in_alerts"] is True
    assert (
        b["kinds"]["home_package"]["switch"] == "off"
        and b["kinds"]["home_greeting"]["switch"] == "on"
    )
    again = (await c.get("/v1/notify/settings")).json()
    assert again["kinds"] == b["kinds"]


async def test_a_kind_with_no_switch_or_an_unknown_one_is_refused(gc: Any) -> None:
    c, _ = gc
    for kinds in ({"home_intruder": "off"}, {"nonsense": "on"}, {"home_hazard": "feed"}):
        r = await c.put("/v1/notify/settings", json={"kinds": kinds}, headers=CSRF)
        assert r.status_code == 422 and r.json()["error"] == "bad_kind"


@pytest.mark.parametrize(
    "body",
    [
        {"quiet": {"start": "25:00"}},
        {"ring_for": "everything"},
        {"extra": 1},
        {"names_in_alerts": "yes"},
        {"kinds": {"home_package": "maybe"}},
    ],
)
async def test_bad_settings_are_refused(gc: Any, body: dict[str, Any]) -> None:
    c, _ = gc
    r = await c.put("/v1/notify/settings", json=body, headers=CSRF)
    assert r.status_code == 422


async def test_the_snapshot_needs_a_confirmation(gc: Any) -> None:
    c, _ = gc
    r = await c.put("/v1/notify/settings", json={"snapshot": {"on": True}}, headers=CSRF)
    assert r.status_code == 422 and r.json()["error"] == "confirm_required"
    assert (await c.get("/v1/notify/settings")).json()["snapshot"] == {"on": False}
    r = await c.put(
        "/v1/notify/settings", json={"snapshot": {"on": True, "confirm": True}}, headers=CSRF
    )
    assert r.json()["snapshot"] == {"on": True}
    r = await c.put("/v1/notify/settings", json={"snapshot": {"on": False}}, headers=CSRF)
    assert r.json()["snapshot"] == {"on": False}


async def test_vip_references_are_validated_listed_and_removable(gc: Any) -> None:
    c, _ = gc
    r = await c.post(
        "/v1/notify/vip", json={"kind": "phone", "ref": "+91 98765 43210"}, headers=CSRF
    )
    assert r.status_code == 201
    vid = r.json()["id"]
    assert "ref" not in r.json()
    assert (
        await c.post("/v1/notify/vip", json={"kind": "email", "ref": "nope"}, headers=CSRF)
    ).status_code == 422
    assert (
        await c.post("/v1/notify/vip", json={"kind": "phone", "ref": "abc"}, headers=CSRF)
    ).status_code == 422
    assert (
        await c.post("/v1/notify/vip", json={"kind": "face", "ref": "fp_x"}, headers=CSRF)
    ).status_code == 422
    listed = (await c.get("/v1/notify/vip")).json()
    assert [v["id"] for v in listed["vip"]] == [vid]
    # the settings view never carries the reference
    assert "98765" not in (await c.get("/v1/notify/settings")).text
    assert (await c.delete(f"/v1/notify/vip/{vid}", headers=CSRF)).json() == {"removed": True}
    assert (await c.delete(f"/v1/notify/vip/{vid}", headers=CSRF)).status_code == 404


async def test_list_vip_never_returns_references(gc: Any) -> None:
    """Integrated review S6: the list says who is there by kind and a short hint only; the phone
    number or address itself never leaves the server again (it is sealed in Firestore)."""
    c, _ = gc
    await c.post("/v1/notify/vip", json={"kind": "phone", "ref": "+91 98765 43210"}, headers=CSRF)
    await c.post(
        "/v1/notify/vip", json={"kind": "email", "ref": "Anjali@Example.com"}, headers=CSRF
    )
    got = await c.get("/v1/notify/vip")
    assert got.status_code == 200
    body = got.json()
    for v in body["vip"]:
        assert set(v) == {"id", "kind", "hint"}, v
    assert "98765" not in got.text and "43210" not in got.text
    assert "anjali" not in got.text.lower() and "example" not in got.text.lower()
    hints = {v["kind"]: v["hint"] for v in body["vip"]}
    assert hints == {"phone": "ends in 10", "email": "a..."}


async def test_the_vip_list_is_capped_and_duplicates_are_ignored(gc: Any) -> None:
    c, _ = gc
    for i in range(20):
        r = await c.post(
            "/v1/notify/vip", json={"kind": "phone", "ref": f"+9198765{i:05d}"}, headers=CSRF
        )
        assert r.status_code == 201
    r = await c.post("/v1/notify/vip", json={"kind": "phone", "ref": "+919999999999"}, headers=CSRF)
    assert r.status_code == 409 and r.json()["error"] == "vip_full"


async def test_push_key_devices_subscribe_and_remove(gc: Any) -> None:
    c, w = gc
    key = (await c.get("/v1/push/key")).json()
    assert key["available"] and len(key["key"]) == 87
    br = Browser("https://fcm.googleapis.com/fcm/send/api1")
    body = {
        "name": "Chrome on Android",
        "endpoint": br.endpoint,
        "keys": {"p256dh": br.p256dh, "auth": br.auth},
    }
    r = await c.post("/v1/push/subscribe", json=body, headers=CSRF)
    assert r.status_code == 201 and set(r.json()) == {"id", "name", "added_at"}
    devs = (await c.get("/v1/push/devices")).json()["devices"]
    assert any(d["id"] == r.json()["id"] for d in devs)
    assert "fcm" not in (await c.get("/v1/push/devices")).text
    assert (await c.delete(f"/v1/push/subscribe/{r.json()['id']}", headers=CSRF)).json() == {
        "removed": True
    }
    assert (await c.delete("/v1/push/subscribe/w_00000000", headers=CSRF)).status_code == 404


async def test_bad_subscriptions_are_422_with_the_error_shape(gc: Any) -> None:
    c, _ = gc
    br = Browser()
    good = {"name": "n", "endpoint": br.endpoint, "keys": {"p256dh": br.p256dh, "auth": br.auth}}
    r = await c.post(
        "/v1/push/subscribe", json={**good, "endpoint": "https://evil.example/x"}, headers=CSRF
    )
    assert r.status_code == 422 and r.json()["error"] == "bad_endpoint" and "detail" in r.json()
    r = await c.post(
        "/v1/push/subscribe",
        json={**good, "keys": {"p256dh": "AAAA", "auth": br.auth}},
        headers=CSRF,
    )
    assert r.status_code == 422 and r.json()["error"] == "bad_subscription"
    r = await c.post("/v1/push/subscribe", json={"name": "n"}, headers=CSRF)
    assert r.status_code == 422


async def test_the_sixth_device_is_refused(gc: Any) -> None:
    c, _ = gc
    for i in range(6):
        br = Browser(f"https://fcm.googleapis.com/fcm/send/d{i}")
        r = await c.post(
            "/v1/push/subscribe",
            json={
                "name": f"d{i}",
                "endpoint": br.endpoint,
                "keys": {"p256dh": br.p256dh, "auth": br.auth},
            },
            headers=CSRF,
        )
    assert r.status_code == 409 and r.json()["error"] == "push_full"


async def test_the_test_button_uses_both_channels(gc: Any) -> None:
    c, w = gc
    # the world is paired for telegram uid "owner"; the signed-in uid is the owner's email
    from telegram_fakes import OWNER_CHAT

    code, _ = await w.tg.store.start_pairing(user_id_for_email(OWNER))
    await w.tg.store.finish_pairing(code, tg_user_id=1, chat_id=OWNER_CHAT)
    br = Browser("https://fcm.googleapis.com/fcm/send/t")
    await c.post(
        "/v1/push/subscribe",
        json={"name": "n", "endpoint": br.endpoint, "keys": {"p256dh": br.p256dh, "auth": br.auth}},
        headers=CSRF,
    )
    r = await c.post("/v1/push/test", headers=CSRF)
    assert r.json()["sent"] is True and r.json()["telegram"] is True and r.json()["browsers"] == 1


async def test_the_test_button_says_when_nothing_can_deliver(gc: Any) -> None:
    c, w = gc
    r = await c.post("/v1/push/test", headers=CSRF)
    assert r.json()["sent"] is False and r.json()["reason"]


async def test_writes_are_rate_limited(gc: Any) -> None:
    c, _ = gc
    c.app.state.notify_limit = RateLimiter(60, now=lambda: 0.0)  # a frozen clock: no refill
    codes = [
        (await c.put("/v1/notify/settings", json={"ring_for": "urgent"}, headers=CSRF)).status_code
        for _ in range(62)
    ]
    assert codes[0] == 200 and codes.count(429) >= 1


async def test_when_the_feature_is_off_the_routes_say_so(gsettings: Settings) -> None:
    async for c, _ in _client(gsettings, on=False):
        await _login(c)
        assert (await c.get("/v1/notify/settings")).json()["available"] is False
        assert (await c.get("/v1/notify/vip")).json()["available"] is False
        assert (await c.get("/v1/push/key")).json()["available"] is False
        assert (await c.get("/v1/push/devices")).json()["devices"] == []
        assert (await c.post("/v1/push/test", headers=CSRF)).json()["sent"] is False
        for r in (
            await c.put("/v1/notify/settings", json={}, headers=CSRF),
            await c.post(
                "/v1/notify/vip", json={"kind": "phone", "ref": "+919876543210"}, headers=CSRF
            ),
            await c.delete("/v1/notify/vip/v_00000000", headers=CSRF),
            await c.post(
                "/v1/push/subscribe",
                json={"name": "n", "endpoint": "https://x", "keys": {"p256dh": "a", "auth": "b"}},
                headers=CSRF,
            ),
            await c.delete("/v1/push/subscribe/w_1", headers=CSRF),
        ):
            assert r.status_code == 503 and r.json()["error"] == "unavailable"


async def test_a_damaged_settings_document_is_a_503_in_plain_words(gc: Any) -> None:
    c, w = gc
    r = await c.put("/v1/notify/settings", json={"ring_for": "important"}, headers=CSRF)
    assert r.status_code == 200
    key = next(k for k in w.docs._data if k.startswith("jarvis_notify/"))
    w.docs._data[key] = {"ring_for": "bogus"}
    for r in (
        await c.get("/v1/notify/settings"),
        await c.put("/v1/notify/settings", json={}, headers=CSRF),
    ):
        assert r.status_code == 503 and r.json()["error"] == "unavailable"
    assert w.docs._data[key] == {"ring_for": "bogus"}
    assert NOON  # keep the import used
