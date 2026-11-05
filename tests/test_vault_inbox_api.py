# tests/test_vault_inbox_api.py -- R2 D9: /v1/vault/inbox (owner only; CSRF on cookie writes; plain
# error shapes; no vendor text; off states in words; audit entries without names).
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from drive_fakes import PDF
from httpx import ASGITransport, AsyncClient
from inbox_fakes import OWNER, PDF_BYTES, Rig, rig
from pydantic import SecretStr

from jarvis.api import create_app
from jarvis.config import AuthMode, Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore

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


async def _client(s: Settings, r: Rig | None) -> AsyncIterator[AsyncClient]:
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        app.state.vault_inbox = r.inbox if r else None  # I1: create_app mounts the routes
        c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        c.app = app  # type: ignore[attr-defined]
        yield c
        await c.aclose()


@pytest.fixture
def r() -> Rig:
    return rig()


@pytest.fixture
async def gc(gsettings: Settings, r: Rig) -> AsyncIterator[AsyncClient]:
    async for c in _client(gsettings, r):
        yield c


async def test_every_route_needs_sign_in(gc: AsyncClient) -> None:
    assert (await gc.get("/v1/vault/inbox")).status_code == 401
    assert (await gc.put("/v1/vault/inbox", json={"folder_id": "inbox1"})).status_code == 401
    assert (await gc.post("/v1/vault/inbox/check")).status_code == 401


async def test_cookie_writes_need_the_csrf_header(gc: AsyncClient) -> None:
    await _login(gc)
    assert (await gc.put("/v1/vault/inbox", json={"folder_id": "inbox1"})).status_code == 403
    assert (await gc.delete("/v1/vault/inbox")).status_code == 403


async def test_pick_view_check_and_switch_off(gc: AsyncClient, r: Rig) -> None:
    await _login(gc)
    v = (await gc.get("/v1/vault/inbox")).json()
    assert v["available"] is True and v["configured"] is False
    assert {f["id"] for f in v["offered"]} == {"inbox1", "use1"}
    p = await gc.put("/v1/vault/inbox", json={"folder_id": "inbox1"}, headers=CSRF)
    assert p.status_code == 200 and p.json()["folder"]["id"] == "inbox1"
    r.drive.file("p1", "dl.pdf", "inbox1", PDF_BYTES, mime=PDF)
    c = await gc.post("/v1/vault/inbox/check", headers=CSRF)
    assert c.status_code == 200 and c.json() == {"imported": 1, "skipped": 0, "more": False}
    d = await gc.delete("/v1/vault/inbox", headers=CSRF)
    assert d.status_code == 200 and d.json()["configured"] is False


async def test_errors_are_plain_and_have_the_standard_shape(gc: AsyncClient) -> None:
    await _login(gc)
    r1 = await gc.put("/v1/vault/inbox", json={"folder_id": "evil"}, headers=CSRF)
    assert r1.status_code == 403 and set(r1.json()) == {"error", "detail"}
    assert r1.json()["error"] == "not_owner" and "stranger" not in r1.text
    await gc.put("/v1/drive/roots/use1", json={"use": True}, headers=CSRF)  # no drive router here
    r2 = await gc.put("/v1/vault/inbox", json={"folder_id": 5}, headers=CSRF)
    assert r2.status_code == 422


async def test_a_use_folder_gets_409_in_use_folder(gc: AsyncClient, r: Rig) -> None:
    await _login(gc)
    await r.svc.set_use(
        "u_" + __import__("hashlib").sha256(OWNER.encode()).hexdigest()[:16], OWNER, "use1", True
    )
    resp = await gc.put("/v1/vault/inbox", json={"folder_id": "use1"}, headers=CSRF)
    assert resp.status_code == 409 and resp.json()["error"] == "in_use_folder"


async def test_drive_not_set_up_says_so(gsettings: Settings) -> None:
    async for c in _client(gsettings, None):
        await _login(c)
        v = (await c.get("/v1/vault/inbox")).json()
        assert v["available"] is False and "isn't set up" in v["note"]
        assert (await c.post("/v1/vault/inbox/check", headers=CSRF)).status_code == 404


async def test_the_drive_row_set_to_never_switches_the_import_off(gc: AsyncClient, r: Rig) -> None:
    await _login(gc)

    class Never:
        async def rules_for(self, uid: str) -> dict[str, Any]:
            return {"drive_list": "never"}

    gc.app.state.permissions = Never()  # type: ignore[attr-defined]
    import jarvis.api.vault_inbox as mod

    async def always(*_: Any) -> bool:
        return True

    orig = mod.is_never
    mod.is_never = always  # type: ignore[assignment]
    try:
        v = (await gc.get("/v1/vault/inbox")).json()
        assert v["available"] is False and "Permissions" in v["note"]
        resp = await gc.post("/v1/vault/inbox/check", headers=CSRF)
        assert resp.status_code == 409 and resp.json()["error"] == "switched_off"
    finally:
        mod.is_never = orig  # type: ignore[assignment]


async def test_storage_trouble_is_a_plain_503(gsettings: Settings, r: Rig) -> None:
    async for c in _client(gsettings, r):
        await _login(c)
        r.docs._data["jarvis_vault_inbox/x"] = {}  # type: ignore[attr-defined]

        async def boom(uid: str) -> None:
            from jarvis.vault_inbox.store import InboxUnreadable

            raise InboxUnreadable("JARVIS couldn't read the DigiLocker import settings just now.")

        r.inbox.store.load = boom  # type: ignore[method-assign]
        resp = await c.get("/v1/vault/inbox")
        assert resp.status_code == 503 and resp.json()["error"] == "inbox_unavailable"


async def test_changes_are_rate_limited(gc: AsyncClient) -> None:
    await _login(gc)
    codes = [
        (await gc.put("/v1/vault/inbox", json={"folder_id": "inbox1"}, headers=CSRF)).status_code
        for _ in range(22)
    ]
    assert codes[0] == 200 and codes[-1] == 429


async def test_audit_entries_carry_no_names(gc: AsyncClient, r: Rig) -> None:
    await _login(gc)
    await gc.put("/v1/vault/inbox", json={"folder_id": "inbox1"}, headers=CSRF)
    entries = [e for e in gc.app.state.gateway.audit._entries if e.agent == "vault_inbox"]  # type: ignore[attr-defined]
    assert entries and "inbox1" not in str(entries) and "JARVIS Vault inbox" not in str(entries)
