# tests/test_privacy_api.py - R2 D14 over HTTP through the real app: GET /v1/privacy, per-category
# export, "download everything" and the delete route with its passkey / re-sign-in paths, 409 on a
# changed rev, console-only (a bearer token can't export or delete) and the error shape.
from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from passkey_fakes import SoftAuthenticator
from privacy_fakes import FakeSource
from pydantic import SecretStr

from jarvis.api import auth as auth_mod
from jarvis.api import create_app
from jarvis.api.identity import user_id_for_email
from jarvis.config import AuthMode, Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.privacy import PrivacyRegistry
from jarvis.privacy.service import PrivacyService
from jarvis.tools import Gateway

ORIGIN = "http://test"
OWNER = "akash@example.com"
UID = user_id_for_email(OWNER)
CSRF = {"X-Requested-With": "JARVIS"}
BEARER = {"Authorization": "Bearer cli-token"}


class Seeded:
    def __init__(self) -> None:
        self.reg = PrivacyRegistry(budget_s=1.0)
        self.places = FakeSource("places", delete="simple", items={})
        self.notes = FakeSource("notes", delete="passkey", items={})
        self.things = FakeSource("things", delete="passkey", items={})
        self.audit_row = FakeSource("audit", delete="none", items={})
        self.vault = FakeSource("vault", delete="passkey", exportable=False, items={})
        for s in (self.places, self.notes, self.things, self.audit_row, self.vault):
            self.reg.register(s)

    def seed(self, uid: str) -> None:
        self.places.items[uid] = ["home"]
        self.notes.items[uid] = ["n1", "n2"]
        self.things.items[uid] = ["t1"]
        self.vault.items[uid] = ["v1"]
        self.notes.items["u_other"] = ["theirs"]


@pytest.fixture
def google_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "auth_mode": AuthMode.GOOGLE,
            "google_client_id": "cid.apps.googleusercontent.com",
            "google_client_secret": SecretStr("gsecret"),
            "owner_emails": [OWNER],
            "session_secret": SecretStr("x" * 32),
            "public_base_url": ORIGIN,
            "api_token": SecretStr("cli-token"),
        }
    )


async def _sign_in(c: AsyncClient, *, reauth: bool = True) -> None:
    async def fake(request: Any) -> dict[str, Any]:
        return {
            "userinfo": {
                "email": OWNER,
                "email_verified": True,
                "sub": "1",
                "auth_time": int(auth_mod._now()),
            }
        }

    c.app.state.oauth.google.authorize_access_token = fake  # type: ignore[attr-defined]
    if reauth:
        await c.get("/auth/login?reauth=1", follow_redirects=False)
    r = await c.get("/auth/callback?code=abc&state=s")
    assert r.status_code in (200, 302, 307), r.text


@pytest.fixture
async def rig(
    google_settings: Settings, provider: MockProvider, gateway: Gateway
) -> AsyncIterator[tuple[AsyncClient, Seeded]]:
    app = create_app(
        google_settings, provider=provider, store=InMemorySessionStore(), gateway=gateway
    )
    seeded = Seeded()
    async with app.router.lifespan_context(app):
        app.state.privacy = PrivacyService(
            seeded.reg, permissions=app.state.permissions, audit=gateway.audit
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as c:
            c.app = app  # type: ignore[attr-defined]
            seeded.seed(UID)
            yield c, seeded


def _cli(c: AsyncClient) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=c.app), base_url=ORIGIN, headers=BEARER)  # type: ignore[attr-defined]


async def _rev(c: AsyncClient, cid: str) -> str:
    r = await c.get("/v1/privacy")
    return next(x["rev"] for x in r.json()["categories"] if x["id"] == cid)


async def _register_passkey(c: AsyncClient, auth: SoftAuthenticator) -> None:
    r = await c.post("/v1/passkeys/register/options", json={}, headers=CSRF)
    assert r.status_code == 200, r.text
    opts = r.json()
    cred = auth.create(opts["public_key"])
    r = await c.post(
        "/v1/passkeys/register",
        json={"challenge_id": opts["challenge_id"], "credential": cred, "label": "Laptop"},
        headers=CSRF,
    )
    assert r.status_code == 200, r.text
    r = await c.put("/v1/permissions", json={"require_passkey": True}, headers=CSRF)
    assert r.status_code == 200, r.text


async def _proof(c: AsyncClient, auth: SoftAuthenticator, **req: Any) -> dict[str, Any]:
    r = await c.post("/v1/passkeys/challenge", json=req, headers=CSRF)
    assert r.status_code == 200, r.text
    ch = r.json()
    return {"challenge_id": ch["challenge_id"], "credential": auth.get(ch["public_key"])}


# ---- view -------------------------------------------------------------------------------------


async def test_get_privacy_lists_every_category_for_the_signed_in_owner(rig: Any) -> None:
    c, _ = rig
    await _sign_in(c)
    r = await c.get("/v1/privacy")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [x["id"] for x in body["categories"]] == ["places", "notes", "things", "audit", "vault"]
    assert {x["id"]: x["count"] for x in body["categories"]}["notes"] == 2
    assert body["passkey_in_force"] is False and body["generated_at"]


async def test_privacy_needs_a_sign_in(rig: Any) -> None:
    c, _ = rig
    assert (await c.get("/v1/privacy")).status_code == 401


async def test_a_bearer_token_may_look_but_not_export_or_delete(rig: Any) -> None:
    c, s = rig
    cli = _cli(c)
    r = await cli.get("/v1/privacy")
    assert r.status_code == 200
    for method, url, body in (
        ("GET", "/v1/privacy/places/export", None),
        ("POST", "/v1/privacy/export-all", {}),
        ("POST", "/v1/privacy/places/delete", {"rev": "x"}),
    ):
        r = await cli.request(method, url, json=body)
        assert r.status_code == 403 and r.json()["error"] == "console_only", (url, r.text)
        assert set(r.json()) >= {"error", "detail"}
    assert s.places.deleted_calls == []


async def test_without_the_service_the_routes_say_not_available(
    google_settings: Settings, provider: MockProvider, gateway: Gateway
) -> None:
    app = create_app(
        google_settings, provider=provider, store=InMemorySessionStore(), gateway=gateway
    )
    async with app.router.lifespan_context(app):
        app.state.privacy = None  # I1: create_app wires the service; here it is missing
        async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as c:
            c.app = app  # type: ignore[attr-defined]
            await _sign_in(c)
            r = await c.get("/v1/privacy")
            assert r.status_code == 404 and r.json()["error"] == "not_found"


# ---- export -----------------------------------------------------------------------------------


async def test_category_export_is_a_json_attachment_without_secrets(rig: Any) -> None:
    c, s = rig
    s.notes.secret = "sk-TOPSECRET"
    await _sign_in(c)
    r = await c.get("/v1/privacy/notes/export")
    assert r.status_code == 200
    assert (
        "attachment" in r.headers["content-disposition"]
        and "notes" in r.headers["content-disposition"]
    )
    assert r.headers["cache-control"] == "no-store"
    assert r.json()["data"]["items"] == ["n1", "n2"]
    assert "TOPSECRET" not in r.text and "theirs" not in r.text


async def test_h1_content_export_needs_a_fresh_sign_in_without_passkeys(rig: Any) -> None:
    c, _ = rig
    await _sign_in(c, reauth=False)
    for r in (
        await c.get("/v1/privacy/notes/export"),
        await c.post("/v1/privacy/notes/export", json={}, headers=CSRF),
    ):
        assert r.status_code == 403, r.text
        assert r.json()["error"] == "proof_required" and r.json()["reason"] == "reauth"
        assert "n1" not in r.text
    # a category he can make again stays a plain export
    assert (await c.get("/v1/privacy/places/export")).status_code == 200
    await _sign_in(c, reauth=True)
    r = await c.post("/v1/privacy/notes/export", json={}, headers=CSRF)
    assert r.status_code == 200 and r.json()["data"]["items"] == ["n1", "n2"]


async def test_h1_content_export_with_a_passkey_in_force_needs_the_export_proof(rig: Any) -> None:
    c, _ = rig
    await _sign_in(c)
    auth = SoftAuthenticator(origin=ORIGIN)
    await _register_passkey(c, auth)
    for r in (
        await c.get("/v1/privacy/notes/export"),
        await c.post("/v1/privacy/notes/export", json={}, headers=CSRF),
    ):
        assert r.status_code == 403 and r.json()["error"] == "passkey_required"
    wrong = await _proof(c, auth, purpose="privacy_export", target="all")
    r = await c.post("/v1/privacy/notes/export", json={"proof": wrong}, headers=CSRF)
    assert r.status_code == 403 and r.json()["error"] == "passkey_rejected"
    proof = await _proof(c, auth, purpose="privacy_export", target="export:notes")
    r = await c.post("/v1/privacy/notes/export", json={"proof": proof}, headers=CSRF)
    assert r.status_code == 200 and r.json()["data"]["items"] == ["n1", "n2"]
    assert (await c.get("/v1/privacy/places/export")).status_code == 200  # simple: no proof


async def test_h1_the_post_export_needs_the_csrf_header(rig: Any) -> None:
    c, _ = rig
    await _sign_in(c)
    r = await c.post("/v1/privacy/notes/export", json={})
    assert r.status_code in (401, 403)


async def test_m4_a_delete_that_left_rows_says_how_many(rig: Any) -> None:
    c, s = rig
    await _sign_in(c)
    s.places.noop_delete = True
    rev = await _rev(c, "places")
    r = await c.post("/v1/privacy/places/delete", json={"rev": rev}, headers=CSRF)
    assert r.status_code == 200
    assert r.json() == {"deleted": 0, "category": "places", "remaining": 1, "pending": ""}


async def test_m5_the_view_carries_the_delete_count(rig: Any) -> None:
    c, _ = rig
    await _sign_in(c)
    notes = next(x for x in (await c.get("/v1/privacy")).json()["categories"] if x["id"] == "notes")
    assert notes["delete_count"] == 2


async def test_export_of_an_unknown_or_unexportable_category(rig: Any) -> None:
    c, _ = rig
    await _sign_in(c)
    assert (await c.get("/v1/privacy/nope/export")).status_code == 404
    r = await c.get("/v1/privacy/vault/export")
    assert r.status_code == 403 and r.json()["error"] == "no_export"
    assert (await c.get("/v1/privacy/Bad..Id/export")).status_code == 422


async def test_download_everything_needs_a_fresh_sign_in_without_passkeys(rig: Any) -> None:
    c, _ = rig
    await _sign_in(c, reauth=False)
    r = await c.post("/v1/privacy/export-all", json={}, headers=CSRF)
    assert r.status_code == 403 and r.json()["error"] == "proof_required"
    assert r.json()["reason"] == "reauth"
    await _sign_in(c, reauth=True)
    r = await c.post("/v1/privacy/export-all", json={}, headers=CSRF)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["categories"]) == {"places", "notes", "things", "audit"}
    assert "Vault" in body["vault_files"]
    assert "attachment" in r.headers["content-disposition"]


async def test_download_everything_with_a_passkey(rig: Any) -> None:
    c, _ = rig
    await _sign_in(c)
    auth = SoftAuthenticator(origin=ORIGIN)
    await _register_passkey(c, auth)
    r = await c.post("/v1/privacy/export-all", json={}, headers=CSRF)
    assert r.status_code == 403 and r.json()["error"] == "passkey_required"
    proof = await _proof(c, auth, purpose="privacy_export", target="all")
    r = await c.post("/v1/privacy/export-all", json={"proof": proof}, headers=CSRF)
    assert r.status_code == 200, r.text


# ---- delete -----------------------------------------------------------------------------------


async def test_a_simple_delete_returns_the_count_and_needs_the_csrf_header(rig: Any) -> None:
    c, s = rig
    await _sign_in(c)
    rev = await _rev(c, "places")
    r = await c.post("/v1/privacy/places/delete", json={"rev": rev})
    assert r.status_code == 403 and r.json()["error"] == "csrf"
    r = await c.post("/v1/privacy/places/delete", json={"rev": rev}, headers=CSRF)
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": 1, "category": "places", "remaining": 0, "pending": ""}
    assert s.places.items[UID] == []


async def test_a_changed_rev_is_409(rig: Any) -> None:
    c, s = rig
    await _sign_in(c)
    rev = await _rev(c, "places")
    s.places.items[UID].append("work")
    r = await c.post("/v1/privacy/places/delete", json={"rev": rev}, headers=CSRF)
    assert r.status_code == 409 and r.json()["error"] == "changed"
    assert s.places.deleted_calls == []


async def test_a_category_with_no_delete_is_403(rig: Any) -> None:
    c, _ = rig
    await _sign_in(c)
    r = await c.post("/v1/privacy/audit/delete", json={"rev": await _rev(c, "audit")}, headers=CSRF)
    assert r.status_code == 403 and r.json()["error"] == "not_deletable"


async def test_passkey_class_without_passkeys_needs_delete_typed_and_a_fresh_sign_in(
    rig: Any,
) -> None:
    c, s = rig
    await _sign_in(c)
    rev = await _rev(c, "notes")
    r = await c.post("/v1/privacy/notes/delete", json={"rev": rev}, headers=CSRF)
    assert r.status_code == 422 and r.json()["error"] == "input_rejected"
    r = await c.post(
        "/v1/privacy/notes/delete", json={"rev": rev, "confirm": "DELETE"}, headers=CSRF
    )
    assert r.status_code == 200 and r.json()["deleted"] == 2
    assert s.notes.items["u_other"] == ["theirs"]


async def test_passkey_class_needs_a_stale_sign_in_to_reauth(rig: Any, monkeypatch: Any) -> None:
    c, _ = rig
    await _sign_in(c)
    rev = await _rev(c, "notes")
    later = time.time() + 6 * 60
    monkeypatch.setattr(auth_mod, "_now", lambda: later)
    r = await c.post(
        "/v1/privacy/notes/delete", json={"rev": rev, "confirm": "DELETE"}, headers=CSRF
    )
    assert r.status_code in (401, 403)


async def test_passkey_class_with_a_passkey_in_force(rig: Any) -> None:
    c, s = rig
    await _sign_in(c)
    auth = SoftAuthenticator(origin=ORIGIN)
    await _register_passkey(c, auth)
    assert (await c.get("/v1/privacy")).json()["passkey_in_force"] is True
    rev = await _rev(c, "notes")
    r = await c.post(
        "/v1/privacy/notes/delete", json={"rev": rev, "confirm": "DELETE"}, headers=CSRF
    )
    assert r.status_code == 403 and r.json()["error"] == "passkey_required"
    assert s.notes.deleted_calls == []
    # a proof made for another category is refused
    wrong = await _proof(
        c, auth, purpose="privacy_delete", target=f"things:{await _rev(c, 'things')}"
    )
    r = await c.post("/v1/privacy/notes/delete", json={"rev": rev, "proof": wrong}, headers=CSRF)
    assert r.status_code == 403 and r.json()["error"] == "passkey_rejected"
    assert s.notes.deleted_calls == []
    # the right one works once, and never twice
    proof = await _proof(c, auth, purpose="privacy_delete", target=f"notes:{rev}")
    r = await c.post("/v1/privacy/notes/delete", json={"rev": rev, "proof": proof}, headers=CSRF)
    assert r.status_code == 200 and r.json() == {
        "deleted": 2,
        "category": "notes",
        "remaining": 0,
        "pending": "",
    }
    s.notes.items[UID] = ["again"]
    rev2 = await _rev(c, "notes")
    r = await c.post("/v1/privacy/notes/delete", json={"rev": rev2, "proof": proof}, headers=CSRF)
    assert r.status_code == 403 and r.json()["error"] == "passkey_rejected"


async def test_a_failing_delete_is_plain_words_and_leaks_nothing(rig: Any) -> None:
    c, s = rig
    await _sign_in(c)
    rev = await _rev(c, "places")
    s.places.fail_delete = True
    r = await c.post("/v1/privacy/places/delete", json={"rev": rev}, headers=CSRF)
    assert r.status_code == 502 and r.json()["error"] == "delete_failed"
    assert "delete failed" not in r.json()["detail"].lower().replace("couldn't delete", "")


async def test_a_bad_body_is_rejected_in_the_apps_shape(rig: Any) -> None:
    c, _ = rig
    await _sign_in(c)
    r = await c.post("/v1/privacy/places/delete", json={"rev": "x", "extra": 1}, headers=CSRF)
    assert r.status_code == 422
    r = await c.post("/v1/privacy/places/delete", json={}, headers=CSRF)
    assert r.status_code == 422


async def test_every_delete_and_export_is_audited_without_content(
    rig: Any, gateway: Gateway
) -> None:
    c, _ = rig
    await _sign_in(c)
    await c.get("/v1/privacy/notes/export")
    rev = await _rev(c, "places")
    await c.post("/v1/privacy/places/delete", json={"rev": rev}, headers=CSRF)
    entries = (await gateway.audit.tail(20)).entries
    tools = [(e.tool, e.agent) for e in entries if e.tool.startswith("privacy_")]
    assert ("privacy_export", "owner") in tools and ("privacy_delete", "owner") in tools
    assert "n1" not in " ".join(e.detail for e in entries)


async def test_the_routes_are_rate_limited(rig: Any) -> None:
    c, _ = rig
    await _sign_in(c)
    codes = [(await c.get("/v1/privacy")).status_code for _ in range(70)]
    assert 429 in codes
