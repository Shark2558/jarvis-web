# tests/test_belongings_api.py -- R2 D11: /v1/things (owner only; CSRF on cookie writes; error shape
# {error, detail}; add-or-move; history; delete + Undo; export is console-only; no key -> says so).
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from belongings_fakes import Things, things
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.api import create_app
from jarvis.api.identity import user_id_for_email
from jarvis.config import AuthMode, Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore

OWNER = "akash@example.com"
UID = user_id_for_email(OWNER)
CSRF = {"X-Requested-With": "JARVIS"}
BEARER = {"Authorization": "Bearer cli-token"}


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


async def _client(s: Settings, t: Things | None) -> AsyncIterator[AsyncClient]:
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        app.state.belongings = t.svc if t else None  # I1: create_app mounts /v1/things
        c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        c.app = app  # type: ignore[attr-defined]
        yield c
        await c.aclose()


@pytest.fixture
def t() -> Things:
    return things()


@pytest.fixture
async def gc(gsettings: Settings, t: Things) -> AsyncIterator[AsyncClient]:
    async for c in _client(gsettings, t):
        await _login(c)
        yield c


async def test_needs_sign_in_and_csrf(gsettings: Settings, t: Things) -> None:
    async for c in _client(gsettings, t):
        assert (await c.get("/v1/things")).status_code == 401
        await _login(c)
        r = await c.post("/v1/things", json={"name": "Passport", "place": "file"})
        assert r.status_code == 403  # no CSRF header


async def test_add_then_move_then_list(gc: AsyncClient) -> None:
    r1 = await gc.post(
        "/v1/things", json={"name": "My passport", "place": "blue file"}, headers=CSRF
    )
    assert r1.status_code == 201 and r1.json()["moved"] is False
    r2 = await gc.post("/v1/things", json={"name": "passport", "place": "almirah"}, headers=CSRF)
    body = r2.json()
    assert r2.status_code == 200 and body["moved"] and body["previous_place"] == "blue file"
    assert body["thing"]["moves"] == 1
    listing = (await gc.get("/v1/things")).json()
    assert listing["available"] and listing["total"] == 1
    assert set(listing["things"][0]) == {
        "id", "name", "place", "note", "holder", "updated_at", "moves",
    }  # fmt: skip
    hit = (await gc.get("/v1/things?q=almirah")).json()
    assert [x["name"] for x in hit["things"]] == ["My passport"]


async def test_edit_history_and_delete_with_undo(gc: AsyncClient, t: Things) -> None:
    made = (
        await gc.post("/v1/things", json={"name": "Keys", "place": "hook"}, headers=CSRF)
    ).json()
    tid = made["thing"]["id"]
    e = await gc.patch(
        f"/v1/things/{tid}", json={"place": "drawer", "holder": "Neha"}, headers=CSRF
    )
    assert e.json()["previous_place"] == "hook" and e.json()["thing"]["holder"] == "Neha"
    h = (await gc.get(f"/v1/things/{tid}/history")).json()
    assert [m["place"] for m in h["earlier"]] == ["hook"]
    d = await gc.delete(f"/v1/things/{tid}", headers=CSRF)
    assert (
        d.status_code == 200
        and d.json()["kind"] == "thing"
        and d.json()["undo_id"].startswith("del_")
    )
    assert (await gc.get("/v1/things")).json()["total"] == 0
    out = await t.undo.restore(UID, d.json()["undo_id"])
    assert out.status.value == "restored"
    assert (await gc.get("/v1/things")).json()["total"] == 1


async def test_errors_have_the_standard_shape(gc: AsyncClient) -> None:
    for body, status, code in (
        ({"name": "", "place": "x"}, 422, "no_name"),
        ({"name": "Card", "place": "card 4111 1111 1111 1111"}, 422, "sensitive"),
        ({"name": "x" * 70, "place": "y"}, 422, "too_long"),
    ):
        r = await gc.post("/v1/things", json=body, headers=CSRF)
        assert (
            r.status_code == status
            and r.json()["error"] == code
            and set(r.json()) == {"error", "detail"}
        )
    r = await gc.delete("/v1/things/t_000000000000", headers=CSRF)
    assert r.status_code == 404 and r.json()["error"] == "not_found"
    assert (
        await gc.post("/v1/things", json={"name": "a", "place": "b", "x": 1}, headers=CSRF)
    ).status_code == 422


async def test_export_is_console_only(gc: AsyncClient, gsettings: Settings, t: Things) -> None:
    await gc.post("/v1/things", json={"name": "Keys", "place": "hook"}, headers=CSRF)
    r = await gc.get("/v1/things/export")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert r.headers["cache-control"] == "no-store" and r.json()["things"][0]["place"] == "hook"
    async for bare in _client(gsettings, t):
        refused = await bare.get("/v1/things/export", headers=BEARER)
        assert refused.status_code == 403 and refused.json()["error"] == "console_only"


async def test_no_key_says_so(gsettings: Settings) -> None:
    async for c in _client(gsettings, None):
        await _login(c)
        v = (await c.get("/v1/things")).json()
        assert v["available"] is False and "no encryption key" in v["reason"]
        r = await c.post("/v1/things", json={"name": "Keys", "place": "hook"}, headers=CSRF)
        assert r.status_code == 503 and r.json()["error"] == "unavailable"


async def test_storage_trouble_is_a_plain_503(gc: AsyncClient, t: Things) -> None:
    from jarvis.belongings.store import ThingsUnavailable

    async def boom(uid: str) -> Any:
        raise ThingsUnavailable("JARVIS couldn't open your list of things just now.")

    t.store.load = boom  # type: ignore[method-assign]
    r = await gc.get("/v1/things")
    assert r.status_code == 503 and r.json()["error"] == "unavailable"


async def test_changes_are_rate_limited(gc: AsyncClient) -> None:
    codes = [
        (
            await gc.post("/v1/things", json={"name": "Keys", "place": "hook"}, headers=CSRF)
        ).status_code
        for _ in range(62)
    ]
    assert codes[-1] == 429 and 429 not in codes[:60]
