# tests/test_faces_api.py -- R3 D13: /v1/faces (owner only; CSRF on cookie writes; error shape
# {error, detail, reason?}; consent 422s; delete behind a passkey bound to face:<id>; no picture).
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from faces_fakes import Faces, faces
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.api import auth as auth_mod
from jarvis.api import create_app
from jarvis.api.faces import install_faces
from jarvis.api.identity import user_id_for_email
from jarvis.config import AuthMode, Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.permissions.errors import PasskeyRejected, PasskeyRequired

OWNER = "akash@example.com"
UID = user_id_for_email(OWNER)
CSRF = {"X-Requested-With": "JARVIS"}
BEARER = {"Authorization": "Bearer cli-token"}
BODY = {
    "name": "Anjali",
    "relation": "friend",
    "child": False,
    "vip": False,
    "given_by": "self",
    "consent_version": "fc1",
    "confirm": True,
}
PROOF = {
    "challenge_id": "c" * 20,
    "credential": {
        "id": "Y3JlZA",
        "rawId": "Y3JlZA",
        "type": "public-key",
        "response": {"clientDataJSON": "e30", "authenticatorData": "YQ", "signature": "c2ln"},
    },
}


@dataclass
class Perms:
    in_force: bool = True
    fail: Exception | None = None
    seen: list[tuple[str, str | None, Any]] = field(default_factory=list)

    async def check_purpose(
        self, uid: str, purpose: str, target: str | None, proof: Any
    ) -> str | None:
        self.seen.append((purpose, target, proof))
        if not self.in_force:
            return None
        if self.fail is not None:
            raise self.fail
        if proof is None:
            raise PasskeyRequired("Approve this with your passkey.")
        return "passkey pk_1"


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
        return {
            "userinfo": {
                "email": OWNER,
                "email_verified": True,
                "sub": OWNER,
                "auth_time": int(auth_mod._now()),
            }
        }

    c.app.state.oauth.google.authorize_access_token = fake  # type: ignore[attr-defined]
    assert (await c.get("/auth/callback?code=abc&state=x")).status_code in (302, 307)


async def _client(s: Settings, f: Faces | None, perms: Perms | None) -> AsyncIterator[AsyncClient]:
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    install_faces(app)  # I1: create_app mounts it
    async with app.router.lifespan_context(app):
        app.state.faces = f.svc if f else None
        app.state.permissions = perms

        async def online(_uid: str) -> bool:
            return True

        app.state.faces_laptop = online
        c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        c.app = app  # type: ignore[attr-defined]
        yield c
        await c.aclose()


@pytest.fixture
def f() -> Faces:
    return faces()


@pytest.fixture
def perms() -> Perms:
    return Perms()


@pytest.fixture
async def gc(gsettings: Settings, f: Faces, perms: Perms) -> AsyncIterator[AsyncClient]:
    async for c in _client(gsettings, f, perms):
        await _login(c)
        yield c


async def test_needs_sign_in_and_csrf(gsettings: Settings, f: Faces) -> None:
    async for c in _client(gsettings, f, None):
        assert (await c.get("/v1/faces")).status_code == 401
        await _login(c)
        assert (await c.post("/v1/faces", json=BODY)).status_code == 403  # no CSRF header


async def test_starts_empty_and_carries_the_statements(gc: AsyncClient) -> None:
    got = (await gc.get("/v1/faces")).json()
    assert got["available"] and got["people"] == [] and got["limit"] == 30
    assert got["statements"]["version"] == "fc1" and "<name> agreed" in got["statements"]["adult"]
    assert "under 18" in got["statements"]["child"]


async def test_add_with_consent_then_list(gc: AsyncClient) -> None:
    r = await gc.post("/v1/faces", json=BODY, headers=CSRF)
    assert r.status_code == 201
    person = r.json()["person"]
    assert person["state"] == "consented" and person["laptop_code"] == person["id"]
    assert person["consent_version"] == "fc1" and person["renewal_due"] is False
    assert (await gc.get("/v1/faces")).json()["people"][0]["name"] == "Anjali"


async def test_consent_errors_are_422_with_their_codes(gc: AsyncClient) -> None:
    r = await gc.post("/v1/faces", json={**BODY, "confirm": False}, headers=CSRF)
    assert r.status_code == 422 and r.json()["error"] == "consent_missing"
    missing = {k: v for k, v in BODY.items() if k != "confirm"}
    assert (await gc.post("/v1/faces", json=missing, headers=CSRF)).json()[
        "error"
    ] == "consent_missing"
    kid = {**BODY, "child": True, "given_by": "self"}
    r2 = await gc.post("/v1/faces", json=kid, headers=CSRF)
    assert r2.status_code == 422 and r2.json()["error"] == "child_needs_guardian"
    assert (await gc.get("/v1/faces")).json()["people"] == []


async def test_duplicate_and_unknown_fields(gc: AsyncClient) -> None:
    await gc.post("/v1/faces", json=BODY, headers=CSRF)
    r = await gc.post("/v1/faces", json=BODY, headers=CSRF)
    assert r.status_code == 409 and r.json()["error"] == "duplicate_name"
    r2 = await gc.post("/v1/faces", json={**BODY, "name": "B", "photo": "x"}, headers=CSRF)
    assert r2.status_code == 422


async def test_patch_edits_and_reconfirms(gc: AsyncClient, f: Faces) -> None:
    pid = (await gc.post("/v1/faces", json=BODY, headers=CSRF)).json()["person"]["id"]
    f.clock.advance(days=400)
    assert (await gc.get("/v1/faces")).json()["people"][0]["renewal_due"] is True
    r = await gc.patch(f"/v1/faces/{pid}", json={"vip": True, "reconfirm": True}, headers=CSRF)
    assert r.json()["person"]["vip"] is True and r.json()["person"]["renewal_due"] is False
    assert (
        await gc.patch("/v1/faces/fp_000000000000", json={"vip": True}, headers=CSRF)
    ).status_code == 404
    assert (
        await gc.patch("/v1/faces/nonsense", json={"vip": True}, headers=CSRF)
    ).status_code == 404


async def test_delete_needs_the_passkey_bound_to_that_person(
    gc: AsyncClient, perms: Perms, f: Faces
) -> None:
    pid = (await gc.post("/v1/faces", json=BODY, headers=CSRF)).json()["person"]["id"]
    r = await gc.post(f"/v1/faces/{pid}/delete", json={}, headers=CSRF)
    assert r.status_code == 403 and r.json()["error"] == "passkey_required"
    assert (await f.store.load(UID)).people[0].state == "consented"
    ok = await gc.post(f"/v1/faces/{pid}/delete", json={"proof": PROOF}, headers=CSRF)
    assert ok.status_code == 200 and ok.json() == {
        "id": pid,
        "deleting": True,
        "waiting_for_laptop": False,
    }
    assert perms.seen[-1][:2] == ("privacy_delete", f"face:{pid}")
    assert (await gc.get("/v1/faces")).json()["total"] == 0
    (entry,) = f.audit.entries
    assert entry["args"] == {"count": 1} and "Anjali" not in str(entry)


async def test_a_rejected_passkey_deletes_nothing(gc: AsyncClient, perms: Perms, f: Faces) -> None:
    pid = (await gc.post("/v1/faces", json=BODY, headers=CSRF)).json()["person"]["id"]
    perms.fail = PasskeyRejected("replayed", "That check was already used.")
    r = await gc.post(f"/v1/faces/{pid}/delete", json={"proof": PROOF}, headers=CSRF)
    assert r.status_code == 403 and r.json()["error"] == "passkey_rejected"
    assert r.json()["reason"] == "replayed"
    assert (await f.store.load(UID)).people[0].state == "consented"


async def test_delete_without_passkeys_needs_a_fresh_sign_in_and_unknown_is_404(
    gsettings: Settings, f: Faces
) -> None:
    async for c in _client(gsettings, f, Perms(in_force=False)):
        await _login(c)
        pid = (await c.post("/v1/faces", json=BODY, headers=CSRF)).json()["person"]["id"]
        stale = await c.post(f"/v1/faces/{pid}/delete", json={}, headers=CSRF)
        assert stale.status_code == 403 and stale.json()["reason"] == "reauth"
        await c.get("/auth/login?reauth=1", follow_redirects=False)
        await _login(c)
        r = await c.post(f"/v1/faces/{pid}/delete", json={}, headers=CSRF)
        assert r.status_code == 200
        missing = await c.post("/v1/faces/fp_000000000000/delete", json={}, headers=CSRF)
        assert missing.status_code == 404  # no proof is asked for someone who isn't there


async def test_a_bearer_token_cannot_delete(gc: AsyncClient, gsettings: Settings, f: Faces) -> None:
    pid = (await gc.post("/v1/faces", json=BODY, headers=CSRF)).json()["person"]["id"]
    async for c in _client(gsettings, f, Perms()):
        r = await c.post(f"/v1/faces/{pid}/delete", json={"proof": PROOF}, headers=BEARER)
        assert r.status_code == 403 and r.json()["error"] == "console_only"
    assert (await f.store.load(UID)).people[0].state == "consented"


async def test_laptop_off_says_waiting(gsettings: Settings) -> None:
    f = faces(online=False)
    async for c in _client(gsettings, f, Perms()):
        await _login(c)
        pid = (await c.post("/v1/faces", json=BODY, headers=CSRF)).json()["person"]["id"]
        r = await c.post(f"/v1/faces/{pid}/delete", json={"proof": PROOF}, headers=CSRF)
        assert r.json()["waiting_for_laptop"] is True
        again = await c.post(f"/v1/faces/{pid}/delete", json={}, headers=CSRF)
        assert again.json()["waiting_for_laptop"] is True  # no second proof asked


async def test_local_page_link_has_no_secret(gc: AsyncClient) -> None:
    assert (await gc.get("/v1/faces/local")).json() == {
        "url": "http://localhost:8098/faces",
        "laptop_online": True,
    }


async def test_no_key_says_so(gsettings: Settings) -> None:
    async for c in _client(gsettings, None, None):
        await _login(c)
        got = (await c.get("/v1/faces")).json()
        assert got["available"] is False and "no encryption key" in got["reason"]
        r = await c.post("/v1/faces", json=BODY, headers=CSRF)
        assert r.status_code == 503 and r.json()["error"] == "unavailable"


async def test_an_unreadable_registry_is_503_in_plain_words(gc: AsyncClient, f: Faces) -> None:
    await gc.post("/v1/faces", json=BODY, headers=CSRF)
    f.docs._data["jarvis_faces/" + UID]["blob"] = "x"  # type: ignore[attr-defined]
    r = await gc.get("/v1/faces")
    assert r.status_code == 503 and "Anjali" not in r.text
