# tests/test_brief_api.py — slice 7: /v1/brief/* (owner-only, CSRF on writes, exact shapes)
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from brief_fakes import BriefGoogle, mail, ms, timed, tokens
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.api import create_app
from jarvis.api.identity import user_id_for_email
from jarvis.config import AuthMode, Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore

OWNER = "akash@example.com"
OTHER = "partner@example.com"
CSRF = {"X-Requested-With": "JARVIS"}
BEARER = {"Authorization": "Bearer cli-token"}
KEY_B64 = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="

TODAY_KEYS = {
    "date",
    "tz",
    "status",
    "brief",
    "settings",
    "due_at",
    "google_connected",
    "ai_available",
    "inbox_available",
    "ai_cost_note",
}
BRIEF_KEYS = {
    "date",
    "tz",
    "status",
    "trigger",
    "created_at",
    "seen_at",
    "data",
    "ai",
    "ai_note",
    "text",
    "error",
    "inbox",
    "ai_calls_today",
    "generations_left",
}
# slice 10 C (review M4): whether the AI consent covers to-do titles
# R1 D: the Deliveries and Family today switches
SETTINGS_KEYS = {
    "enabled",
    "time",
    "ai_summary",
    "inbox_delivery",
    "updated_at",
    "ai_todo_consent",
    "deliveries",
    "family",
    "vault",  # R2 D5: the Documents section switch
    "home",  # R3: the Home overnight section switch
}


@pytest.fixture
def gsettings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "auth_mode": AuthMode.GOOGLE,
            "google_client_id": "cid.apps.googleusercontent.com",
            "google_client_secret": SecretStr("gsecret"),
            "owner_emails": [OWNER, OTHER],
            "session_secret": SecretStr("x" * 32),
            "public_base_url": "http://test",
            "api_token": SecretStr("cli-token"),
            "token_key": SecretStr(KEY_B64),
        }
    )


@pytest.fixture
async def gc(gsettings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(gsettings, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            c.app = app  # type: ignore[attr-defined]
            yield c


async def _login(c: AsyncClient, email: str) -> None:
    async def fake(request: Any) -> dict[str, Any]:
        return {"userinfo": {"email": email, "email_verified": True, "sub": email}}

    c.app.state.oauth.google.authorize_access_token = fake  # type: ignore[attr-defined]
    assert (await c.get("/auth/callback?code=a&state=b")).status_code in (302, 307)


async def _link(c: AsyncClient, *, insert: bool = True) -> BriefGoogle:
    fake = BriefGoogle(
        events=[timed("e1", "Standup", "2027-01-15T09:30", "2027-01-15T10:00")],
        messages=[
            mail("m1", "Priya <p@x.com>", "Budget", internal_ms=ms("2027-01-15T06:40:00+05:30"))
        ],
    )
    google = c.app.state.google  # type: ignore[attr-defined]
    google.http = fake.client()
    await google.store.put(user_id_for_email(OWNER), tokens(insert=insert))
    return fake


# ---- auth + CSRF ------------------------------------------------------------------------------


async def test_every_route_needs_the_owner(gc: AsyncClient) -> None:
    assert (await gc.get("/v1/brief/today")).status_code == 401
    assert (await gc.get("/v1/brief/settings")).status_code == 401
    assert (await gc.post("/v1/brief/generate", json={}, headers=CSRF)).status_code == 401
    assert (await gc.post("/v1/brief/seen", json={"date": "2027-01-15"})).status_code == 401
    assert (await gc.put("/v1/brief/settings", json={}, headers=CSRF)).status_code == 401
    assert (await gc.get("/v1/brief/today", headers=BEARER)).status_code == 200


async def test_cookie_writes_need_the_csrf_header(gc: AsyncClient) -> None:
    await _login(gc, OWNER)
    for method, path, body in (
        ("POST", "/v1/brief/generate", {}),
        ("POST", "/v1/brief/seen", {"date": "2027-01-15"}),
        ("PUT", "/v1/brief/settings", {"time": "06:30"}),
    ):
        r = await gc.request(method, path, json=body)
        assert r.status_code == 403 and r.json()["error"] == "csrf", path
    assert (
        await gc.put("/v1/brief/settings", json={"time": "06:30"}, headers=CSRF)
    ).status_code == 200


# ---- shapes -------------------------------------------------------------------------------------


async def test_today_and_generate_shapes(gc: AsyncClient) -> None:
    await _login(gc, OWNER)
    fake = await _link(gc)
    t = (await gc.get("/v1/brief/today")).json()
    assert set(t) == TODAY_KEYS and t["status"] == "none" and t["brief"] is None
    assert set(t["settings"]) == SETTINGS_KEYS and t["google_connected"] is True
    assert t["inbox_available"] is True and t["ai_available"] is True
    r = await gc.post("/v1/brief/generate", headers=CSRF)  # no body at all: the console's "open"
    assert r.status_code == 200
    g = r.json()
    assert set(g) == TODAY_KEYS and g["status"] == "ready" and set(g["brief"]) == BRIEF_KEYS
    b = g["brief"]
    assert b["trigger"] == "open" and b["inbox"] == {
        "status": "off",
        "at": None,
        "message_id": None,
    }
    assert set(b["data"]) == {
        "date",
        "tz",
        "calendar",
        "inbox",
        "jarvis",
        "todo",
        "deliveries",  # R1: null until the section is wired and on
        "family",
        "vault",  # R2: null until wired and something is due
        "home",  # R3: null until wired and something happened overnight
        "vitals",  # R4: null until the board has a red / amber line or a spend line
        "helpers",  # R11: null until a helper has a line today
        "sleep",  # R7 I0 seam 23: null until Part D's day builder keeps a night
        "sections_status",
    }
    assert b["data"]["sleep"] is None
    assert set(b["data"]["calendar"]) == {"today", "clashes", "free_blocks", "tomorrow_first"}
    assert set(b["data"]["inbox"]) == {
        "total",
        "items",
        "groups",
        "withheld",
        "exact",
        "failed",
        "listed",
    }  # R11.1 D20 (INTEGRATION-A 3.4)
    # slice 10 C: this link has no Tasks scope, so the to-do section says so (and asked nothing)
    assert b["data"]["todo"] is None
    assert b["data"]["sections_status"] == {
        "calendar": "ok",
        "inbox": "ok",
        "jarvis": "ok",
        "todo": "not_granted",
        "deliveries": "ok",
        "family": "ok",
        "vault": "ok",
        "home": "ok",
        "vitals": "ok",
        "helpers": "ok",  # R11
    }
    assert {r.method for r in fake.requests} == {"GET"}
    forced = (await gc.post("/v1/brief/generate", json={"force": True}, headers=CSRF)).json()
    assert forced["brief"]["trigger"] == "manual"


async def test_seen_shape_404_and_422(gc: AsyncClient) -> None:
    await _login(gc, OWNER)
    t = (await gc.post("/v1/brief/generate", json={}, headers=CSRF)).json()
    r = await gc.post("/v1/brief/seen", json={"date": t["date"]}, headers=CSRF)
    assert r.status_code == 200
    assert set(r.json()) == {"ok", "date", "seen_at"} and r.json()["ok"] is True
    assert (await gc.get("/v1/brief/today")).json()["brief"]["seen_at"] == r.json()["seen_at"]
    missing = await gc.post("/v1/brief/seen", json={"date": "2000-01-01"}, headers=CSRF)
    assert missing.status_code == 404 and missing.json()["error"] == "not_found"
    for bad in ({"date": "15/01/2027"}, {"date": "2027-1-5"}, {"date": 20270115}, {}):
        assert (await gc.post("/v1/brief/seen", json=bad, headers=CSRF)).status_code == 422


# ---- settings ---------------------------------------------------------------------------------


async def test_settings_confirmations_time_and_scope_are_422(gc: AsyncClient) -> None:
    await _login(gc, OWNER)
    await _link(gc, insert=False)
    put = gc.put
    for body, word in (
        ({"ai_summary": True}, "confirm"),
        ({"inbox_delivery": True}, "confirmation"),
        ({"time": "12:00"}, "04:00"),
        ({"time": "07:15"}, "04:00"),
        ({"time": "٠٧:٠٠"}, "04:00"),  # Arabic-Indic digits (F9)
        ({"inbox_delivery": True, "confirm_inbox": True}, "Reconnect Google"),
    ):
        r = await put("/v1/brief/settings", json=body, headers=CSRF)
        assert r.status_code == 422 and r.json()["error"] == "invalid_settings", body
        assert word in r.json()["detail"]
    # a confirm flag must be the JSON literal true
    r = await put(
        "/v1/brief/settings", json={"ai_summary": True, "confirm_spend": "true"}, headers=CSRF
    )
    assert r.status_code == 422
    ok = await put(
        "/v1/brief/settings",
        json={"ai_summary": True, "confirm_spend": True, "time": "06:30"},
        headers=CSRF,
    )
    assert ok.status_code == 200 and set(ok.json()) == SETTINGS_KEYS
    assert ok.json()["ai_summary"] is True and ok.json()["time"] == "06:30"
    assert (await gc.get("/v1/brief/settings")).json() == ok.json()


async def test_inbox_on_with_the_scope_and_confirmation(gc: AsyncClient) -> None:
    await _login(gc, OWNER)
    await _link(gc, insert=True)
    r = await gc.put(
        "/v1/brief/settings", json={"inbox_delivery": True, "confirm_inbox": True}, headers=CSRF
    )
    assert r.status_code == 200 and r.json()["inbox_delivery"] is True


async def test_settings_are_per_owner_and_ignore_a_client_user_id(gc: AsyncClient) -> None:
    await _login(gc, OWNER)
    other = user_id_for_email(OTHER)
    await gc.put("/v1/brief/settings", json={"time": "05:00", "user_id": other}, headers=CSRF)
    await _login(gc, OTHER)
    assert (await gc.get("/v1/brief/settings")).json()["time"] == "07:00"
    await _login(gc, OWNER)
    assert (await gc.get("/v1/brief/settings")).json()["time"] == "05:00"


# ---- limits -------------------------------------------------------------------------------------


async def test_generate_past_the_daily_limit_is_a_friendly_429(gc: AsyncClient) -> None:
    await _login(gc, OWNER)
    for _ in range(6):
        r = await gc.post("/v1/brief/generate", json={"force": True}, headers=CSRF)
        assert r.status_code == 200
    r = await gc.post("/v1/brief/generate", json={"force": True}, headers=CSRF)
    assert r.status_code == 429 and r.json()["error"] == "brief_limit"
    assert "tomorrow" in r.json()["detail"]
    # without force the existing brief is simply returned
    assert (await gc.post("/v1/brief/generate", json={}, headers=CSRF)).status_code == 200


async def test_token_mode_dev_works_without_google(client: AsyncClient) -> None:
    t = (await client.post("/v1/brief/generate", json={"force": True})).json()
    assert t["status"] == "ready" and t["google_connected"] is False
    assert t["brief"]["data"]["sections_status"]["calendar"] == "not_connected"
