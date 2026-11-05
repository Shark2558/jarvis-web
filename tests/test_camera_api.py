# tests/test_camera_api.py -- R3 B: /v1/home alarm, cameras, feed, history. Owner only; CSRF on
# cookie writes; error shape {error, detail, reason?}; disarm is console-only and needs the
# passkey for this home and arm rev; arming is pending until the laptop acks.
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from camera_fakes import HOME, T0, Rig, rig
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.api import create_app
from jarvis.api.camera import install_camera
from jarvis.api.identity import user_id_for_email
from jarvis.camera.service import CameraServices
from jarvis.config import AuthMode, Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.permissions.errors import PasskeyRequired

OWNER = "akash@example.com"
UID = user_id_for_email(OWNER)
CSRF = {"X-Requested-With": "JARVIS"}
BEARER = {"Authorization": "Bearer cli-token"}


class Perms:
    def __init__(self) -> None:
        self.target: str | None = None
        self.in_force = True

    async def check_purpose(self, uid: str, purpose: str, target: str | None, proof: Any) -> Any:
        assert purpose == "home_disarm"
        if not self.in_force:
            return None
        if proof is None or target != self.target:
            raise PasskeyRequired("Use your passkey to switch off the alarm.")
        return "passkey ab12cd34"


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


async def _login(c: AsyncClient) -> None:
    async def fake(request: Any) -> dict[str, Any]:
        return {"userinfo": {"email": OWNER, "email_verified": True, "sub": OWNER}}

    c.app.state.oauth.google.authorize_access_token = fake  # type: ignore[attr-defined]
    assert (await c.get("/auth/callback?code=abc&state=x")).status_code in (302, 307)


def services(r: Rig) -> CameraServices:
    from jarvis.camera.service import build_camera

    s = build_camera(
        docs=r.docs,
        keyring=r.config._doc._ring,  # noqa: SLF001
        caller=r.caller,
        faces=r.faces,
        notifier=r.notifier,
        homes=r.homes,
        permissions=Perms(),
        snapshots=r.snap,
        tz="Asia/Kolkata",
        clock=r.clock,
    )
    return s


async def _client(s: Settings, svc: CameraServices | None) -> AsyncIterator[AsyncClient]:
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        install_camera(app)  # I1 does this in create_app
        app.state.camera = svc
        c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        c.app = app  # type: ignore[attr-defined]
        yield c
        await c.aclose()


@pytest.fixture
async def env(gsettings: Settings) -> AsyncIterator[tuple[AsyncClient, Rig, CameraServices]]:
    r = await rig()
    svc = services(r)
    async for c in _client(gsettings, svc):
        await _login(c)
        yield c, r, svc


async def test_needs_sign_in_and_csrf(gsettings: Settings) -> None:
    r = await rig()
    async for c in _client(gsettings, services(r)):
        assert (await c.get("/v1/home/alarm")).status_code == 401
        await _login(c)
        assert (await c.post("/v1/home/arm", json={})).status_code == 403  # no CSRF header


async def test_without_the_service_the_panel_says_so(gsettings: Settings) -> None:
    async for c in _client(gsettings, None):
        await _login(c)
        body = (await c.get("/v1/home/alarm")).json()
        assert body["available"] is False and "no encryption key" in body["reason"]
        assert (await c.get("/v1/home/feed")).json()["items"] == []
        r = await c.post("/v1/home/arm", json={}, headers=CSRF)
        assert r.status_code == 503 and r.json()["error"] == "unavailable"


async def test_arm_is_pending_until_the_laptop_acks(env: Any) -> None:
    c, r, svc = env
    got = await c.post("/v1/home/arm", json={"mode": "night"}, headers=CSRF)
    assert got.status_code == 200
    body = got.json()
    assert body["armed"] is True and body["mode"] == "night" and body["confirmed"] is False
    assert body["pending_since"] is not None and body["set_via"] == "console"
    await svc.alarm.ack(UID, 1)
    body = (await c.get("/v1/home/alarm")).json()
    assert body["confirmed"] is True and body["pending_since"] is None


async def test_disarm_without_a_passkey_is_403_and_the_alarm_stays_on(env: Any) -> None:
    c, r, svc = env
    await c.post("/v1/home/arm", json={}, headers=CSRF)
    got = await c.post("/v1/home/disarm", json={}, headers=CSRF)
    assert got.status_code == 403 and got.json()["error"] == "passkey_required"
    assert (await c.get("/v1/home/alarm")).json()["armed"] is True


async def test_disarm_with_a_passkey_for_this_home_and_rev_works_and_is_audited(env: Any) -> None:
    c, r, svc = env
    await c.post("/v1/home/arm", json={}, headers=CSRF)
    svc.gate.permissions.target = f"{HOME}:1"  # type: ignore[union-attr]
    proof = _proof()
    got = await c.post("/v1/home/disarm", json={"proof": proof}, headers=CSRF)
    assert got.status_code == 200 and got.json()["armed"] is False
    tail = await c.app.state.gateway.audit.tail(20)  # type: ignore[attr-defined]
    entries = [e for e in tail.entries if e.tool == "home_disarm"]
    assert entries and "passkey ab12cd34" in entries[-1].detail


def _proof() -> dict[str, Any]:
    return {
        "challenge_id": "c" * 22,
        "credential": {
            "id": "AAAA",
            "rawId": "AAAA",
            "type": "public-key",
            "response": {
                "clientDataJSON": "AAAA",
                "authenticatorData": "AAAA",
                "signature": "AAAA",
            },
        },
    }


async def test_a_proof_for_another_rev_is_refused(env: Any) -> None:
    c, r, svc = env
    await c.post("/v1/home/arm", json={}, headers=CSRF)
    svc.gate.permissions.target = f"{HOME}:9"  # type: ignore[union-attr]
    got = await c.post("/v1/home/disarm", json={"proof": _proof()}, headers=CSRF)
    assert got.status_code == 403 and (await c.get("/v1/home/alarm")).json()["armed"] is True


async def test_a_bearer_token_can_never_disarm(env: Any) -> None:
    c, r, svc = env
    await c.post("/v1/home/arm", json={}, headers=CSRF)
    svc.gate.permissions.in_force = False  # type: ignore[union-attr]
    from httpx import ASGITransport as T

    async with AsyncClient(transport=T(app=c.app), base_url="http://test") as bearer:  # type: ignore[attr-defined]
        got = await bearer.post("/v1/home/disarm", json={}, headers=BEARER)
    assert got.status_code == 403 and got.json()["error"] == "console_only"
    assert (await c.get("/v1/home/alarm")).json()["armed"] is True


async def test_without_passkeys_a_fresh_sign_in_is_enough(env: Any) -> None:
    c, r, svc = env
    await c.post("/v1/home/arm", json={}, headers=CSRF)
    svc.gate.permissions.in_force = False  # type: ignore[union-attr]
    stale = await c.post("/v1/home/disarm", json={}, headers=CSRF)
    assert stale.status_code == 403 and stale.json()["reason"] == "reauth"
    await c.get("/auth/login?reauth=1", follow_redirects=False)
    await _login(c)
    got = await c.post("/v1/home/disarm", json={}, headers=CSRF)
    assert got.status_code == 200 and got.json()["armed"] is False


async def test_disarming_an_already_disarmed_home_is_a_quiet_no_op(env: Any) -> None:
    c, r, svc = env
    got = await c.post("/v1/home/disarm", json={}, headers=CSRF)
    assert got.status_code == 200 and got.json()["armed"] is False and svc.alarm is not None


async def test_cameras_round_trip_and_validation(env: Any) -> None:
    c, r, svc = env
    put = await c.put(
        "/v1/home/cameras",
        json={
            "cameras": {
                "gate": {"label": "Front gate", "alarm_zones": ["gate"], "package_zone": "doorstep"}
            },
            "retention_days": 10,
        },
        headers=CSRF,
    )
    assert put.status_code == 200
    body = put.json()
    assert body["cameras"][0]["label"] == "Front gate" and body["retention_days"] == 10
    assert body["model_note"] and "step 12" in body["model_note"]
    bad = await c.put(
        "/v1/home/cameras",
        json={"cameras": {"../x": {"label": "x"}}},
        headers=CSRF,
    )
    assert bad.status_code == 422
    bad = await c.put(
        "/v1/home/cameras",
        json={"cameras": {"gate": {"label": "x", "alarm_zones": ["a b"]}}},
        headers=CSRF,
    )
    assert bad.status_code == 422


async def test_feed_lists_today_and_yesterday(env: Any) -> None:
    c, r, svc = env
    got = await c.get("/v1/home/feed?day=yesterday")
    assert got.status_code == 200 and got.json()["items"] == []
    assert (await c.get("/v1/home/feed?day=tomorrow")).status_code == 422


async def test_history_through_the_bridge_and_plain_words_when_the_laptop_is_off(env: Any) -> None:
    from datetime import UTC, datetime, timedelta

    c, r, svc = env
    r.caller.replies[("GET", "/bridge/v1/events")] = {"events": []}
    start = (datetime.fromtimestamp(T0, UTC) - timedelta(hours=2)).isoformat()
    end = datetime.fromtimestamp(T0, UTC).isoformat()
    ok = await c.get("/v1/home/history", params={"from": start, "to": end, "what": "person"})
    assert ok.status_code == 200 and ok.json()["count"] == 0
    bad = await c.get("/v1/home/history", params={"from": start, "to": end, "what": "bogus"})
    assert bad.status_code == 422 and bad.json()["error"] == "input_rejected"
    r.caller.online = False
    off = await c.get("/v1/home/history", params={"from": start, "to": end})
    assert off.status_code == 503 and "home laptop is off" in off.json()["detail"]


async def test_arm_with_no_alarm_zones_is_flagged_everywhere(env: Any) -> None:
    c, r, svc = env
    got = await c.post("/v1/home/arm", json={}, headers=CSRF)
    body = got.json()
    assert body["armed"] is True and body["zones_configured"] is False
    assert "not protecting anything yet" in body["warning"]
    assert (await c.get("/v1/home/alarm")).json()["zones_configured"] is False


async def test_arm_with_a_zone_has_no_warning(env: Any) -> None:
    from jarvis.camera.models import CameraConfig

    c, r, svc = env
    cam = CameraConfig(label="Gate", alarm_zones=("gate",))
    await r.config.set_cameras(UID, {"gate": cam})
    body = (await c.post("/v1/home/arm", json={}, headers=CSRF)).json()
    assert body["zones_configured"] is True and body.get("warning") is None
