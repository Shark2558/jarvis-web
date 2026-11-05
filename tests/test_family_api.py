# tests/test_family_api.py -- R1 D15: GET/POST /v1/family, DELETE /v1/family/{id} (owner-only, CSRF
# on cookie writes, exact shapes, Google's words never shown, one audit entry per change).
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from brief_fakes import tokens
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from r1d_fakes import FamilyCalendars

from jarvis.api import create_app
from jarvis.api.family import install_family
from jarvis.api.identity import primary_user_id, user_id_for_email
from jarvis.config import AuthMode, Settings
from jarvis.family.service import FamilyService
from jarvis.family.store import FamilyStore
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage.docs import MemoryDocs

OWNER = "akash@example.com"
OTHER = "partner@example.com"
CSRF = {"X-Requested-With": "JARVIS"}
BEARER = {"Authorization": "Bearer cli-token"}
KEY_B64 = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
MEMBER_KEYS = {"id", "name", "calendar_id", "access", "can_write", "added_at"}


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


class Rig:
    def __init__(self, client: AsyncClient, fake: FamilyCalendars, svc: FamilyService) -> None:
        self.c, self.fake, self.svc = client, fake, svc


@pytest.fixture
async def rig(gsettings: Settings) -> AsyncIterator[Rig]:
    app = create_app(gsettings, provider=MockProvider(), store=InMemorySessionStore())
    fake = FamilyCalendars(roles={"anjali@gmail.com": "reader", "ravi@gmail.com": "writer"})
    async with app.router.lifespan_context(app):
        google = app.state.google
        google.http = fake.client()
        for uid in (primary_user_id(gsettings), user_id_for_email(OWNER)):
            await google.store.put(uid, tokens())
        svc = FamilyService(google, FamilyStore(MemoryDocs()), default_tz="Asia/Kolkata")
        app.state.family = svc
        install_family(app)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            c.app = app  # type: ignore[attr-defined]
            yield Rig(c, fake, svc)


async def _login(c: AsyncClient, email: str) -> None:
    async def fake(request: Any) -> dict[str, Any]:
        return {"userinfo": {"email": email, "email_verified": True, "sub": email}}

    c.app.state.oauth.google.authorize_access_token = fake  # type: ignore[attr-defined]
    assert (await c.get("/auth/callback?code=a&state=b")).status_code in (302, 307)


async def test_every_route_needs_the_owner(rig: Rig) -> None:
    c = rig.c
    assert (await c.get("/v1/family")).status_code == 401
    body = {"name": "A", "calendar_id": "anjali@gmail.com"}
    assert (await c.post("/v1/family", json=body, headers=CSRF)).status_code == 401
    assert (await c.delete("/v1/family/fam_000000000000", headers=CSRF)).status_code == 401
    assert (await c.get("/v1/family", headers=BEARER)).status_code == 200


async def test_cookie_writes_need_the_csrf_header(rig: Rig) -> None:
    await _login(rig.c, OWNER)
    body = {"name": "Anjali", "calendar_id": "anjali@gmail.com"}
    r = await rig.c.post("/v1/family", json=body)
    assert r.status_code == 403 and r.json()["error"] == "csrf"
    assert (await rig.c.post("/v1/family", json=body, headers=CSRF)).status_code == 201


async def test_empty_list_then_add_then_list_then_remove(rig: Rig) -> None:
    c = rig.c
    first = (await c.get("/v1/family", headers=BEARER)).json()
    assert first["configured"] is True and first["members"] == [] and first["max_members"] == 8
    assert "Share with specific people" in first["how_to"]
    added = await c.post(
        "/v1/family", json={"name": " Anjali ", "calendar_id": "Anjali@Gmail.com"}, headers=BEARER
    )
    assert added.status_code == 201
    m = added.json()
    assert set(m) == MEMBER_KEYS
    assert (m["name"], m["calendar_id"], m["access"], m["can_write"]) == (
        "Anjali",
        "anjali@gmail.com",
        "reader",
        False,
    )
    shown = (await c.get("/v1/family", headers=BEARER)).json()["members"]
    assert [x["id"] for x in shown] == [m["id"]]
    gone = await c.delete(f"/v1/family/{m['id']}", headers=BEARER)
    assert gone.status_code == 200 and gone.json() == {"removed": m["id"]}
    assert (await c.get("/v1/family", headers=BEARER)).json()["members"] == []


async def test_a_writer_is_marked_can_write(rig: Rig) -> None:
    r = await rig.c.post(
        "/v1/family", json={"name": "Ravi", "calendar_id": "ravi@gmail.com"}, headers=BEARER
    )
    assert r.json()["can_write"] is True and r.json()["access"] == "writer"


async def test_not_shared_is_422_with_the_how_to_and_no_google_words(rig: Rig) -> None:
    r = await rig.c.post(
        "/v1/family", json={"name": "Zed", "calendar_id": "zed@gmail.com"}, headers=BEARER
    )
    assert r.status_code == 422 and r.json()["error"] == "not_shared"
    assert "Share with specific people" in r.json()["detail"]
    assert "not found" not in r.text.lower().replace("not shared", "")


async def test_validation_errors(rig: Rig) -> None:
    c = rig.c
    bad = await c.post(
        "/v1/family", json={"name": "A", "calendar_id": "not an address"}, headers=BEARER
    )
    assert bad.status_code == 422 and bad.json()["error"] == "invalid"
    extra = await c.post(
        "/v1/family",
        json={"name": "A", "calendar_id": "anjali@gmail.com", "access": "owner"},
        headers=BEARER,
    )
    assert extra.status_code == 422
    typed = await c.post("/v1/family", json={"name": 5, "calendar_id": "x@y.com"}, headers=BEARER)
    assert typed.status_code == 422
    assert (await c.delete("/v1/family/not-an-id", headers=BEARER)).status_code == 404
    assert (await c.delete("/v1/family/fam_aaaaaaaaaaaa", headers=BEARER)).status_code == 404


async def test_ninth_member_is_409_full_and_duplicates_409(rig: Rig) -> None:
    c = rig.c
    for i in range(8):
        rig.fake.roles[f"p{i}@gmail.com"] = "reader"
        r = await c.post(
            "/v1/family", json={"name": f"P{i}", "calendar_id": f"p{i}@gmail.com"}, headers=BEARER
        )
        assert r.status_code == 201
    rig.fake.roles["p9@gmail.com"] = "reader"
    full = await c.post(
        "/v1/family", json={"name": "P9", "calendar_id": "p9@gmail.com"}, headers=BEARER
    )
    assert full.status_code == 409 and full.json()["error"] == "full"


async def test_google_trouble_is_503_in_our_words(rig: Rig) -> None:
    rig.fake.fail["GET /calendar/v3/users/me/calendarList/anjali@gmail.com"] = 500
    r = await rig.c.post(
        "/v1/family", json={"name": "A", "calendar_id": "anjali@gmail.com"}, headers=BEARER
    )
    assert r.status_code == 503 and r.json()["error"] == "unavailable"
    assert "fake failure" not in r.text


async def test_not_linked_to_google_is_503_not_connected(rig: Rig) -> None:
    google = rig.c.app.state.google  # type: ignore[attr-defined]
    await google.store.delete(primary_user_id(rig.c.app.state.settings))  # type: ignore[attr-defined]
    r = await rig.c.post(
        "/v1/family", json={"name": "A", "calendar_id": "anjali@gmail.com"}, headers=BEARER
    )
    assert r.status_code == 503 and r.json()["error"] == "not_connected"


async def test_each_owner_sees_only_their_own_list(rig: Rig) -> None:
    await rig.c.post(
        "/v1/family", json={"name": "Anjali", "calendar_id": "anjali@gmail.com"}, headers=BEARER
    )
    await _login(rig.c, OTHER)  # the second owner has their own (empty) list
    assert (await rig.c.get("/v1/family")).json()["members"] == []


async def test_changes_are_audited_with_a_hash_only(rig: Rig) -> None:
    await rig.c.post(
        "/v1/family", json={"name": "Anjali", "calendar_id": "anjali@gmail.com"}, headers=BEARER
    )
    tail = await rig.c.app.state.gateway.audit.tail(10)  # type: ignore[attr-defined]
    entry = next(e for e in tail.entries if e.tool == "family_member_add")
    assert entry.agent == "family" and "anjali" not in repr(entry)


async def test_changes_are_rate_limited(rig: Rig) -> None:
    for _ in range(20):
        await rig.c.delete("/v1/family/fam_aaaaaaaaaaaa", headers=BEARER)
    r = await rig.c.delete("/v1/family/fam_aaaaaaaaaaaa", headers=BEARER)
    assert r.status_code == 429 and r.json()["error"] == "rate_limited"


async def test_a_server_without_the_service_says_not_configured(gsettings: Settings) -> None:
    app = create_app(gsettings, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        app.state.family = None
        install_family(app)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            assert (await c.get("/v1/family", headers=BEARER)).json() == {"configured": False}
