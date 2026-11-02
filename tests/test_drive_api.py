# tests/test_drive_api.py — slice 12 D1: /v1/drive (owner only). GET → JARVIS's address to share
# with, the folders shared with it by the owner (with a confirmed flag) and how many others;
# PUT /v1/drive/roots/{id} {use} — cookie writes need the CSRF header; only the signed-in owner's
# own shared folders can be switched on; errors {error, detail}; no vendor text. Off → 404.
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from drive_fakes import FakeDrive, StaticTokens
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.api import create_app
from jarvis.config import AuthMode, Settings
from jarvis.drive.client import DriveClient
from jarvis.drive.roots import RootsStore
from jarvis.drive.service import DriveService, build_drive_service, drive_configured
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage.docs import MemoryDocs

OWNER = "akash@example.com"
CSRF = {"X-Requested-With": "JARVIS"}
SA = "jarvis-run@proj-123.iam.gserviceaccount.com"


class Tokens(StaticTokens):
    async def email(self) -> str:
        return SA


def _fake() -> FakeDrive:
    d = FakeDrive()
    d.folder("root1", "Registry", shared_by=OWNER)
    d.folder("root2", "Minutes", shared_by=OWNER)
    d.folder("evil", "Free money", shared_by="stranger@evil.example")
    return d


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
            "drive": True,
        }
    )


async def _client(s: Settings, d: FakeDrive) -> AsyncIterator[AsyncClient]:
    svc = DriveService(DriveClient(Tokens(), http=d.client()), RootsStore(MemoryDocs()))
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore(), drive=svc)
    async with app.router.lifespan_context(app):
        c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        c.app = app  # type: ignore[attr-defined]
        yield c
        await c.aclose()


@pytest.fixture
def drive() -> FakeDrive:
    return _fake()


@pytest.fixture
async def gc(gsettings: Settings, drive: FakeDrive) -> AsyncIterator[AsyncClient]:
    async for c in _client(gsettings, drive):
        yield c


async def _login(c: AsyncClient, email: str = OWNER) -> None:
    async def fake(request: Any) -> dict[str, Any]:
        return {"userinfo": {"email": email, "email_verified": True, "sub": email}}

    c.app.state.oauth.google.authorize_access_token = fake  # type: ignore[attr-defined]
    r = await c.get("/auth/callback?code=abc&state=x")
    assert r.status_code in (302, 307)


async def test_get_needs_sign_in(gc: AsyncClient) -> None:
    assert (await gc.get("/v1/drive")).status_code == 401


async def test_get_shows_the_address_and_only_the_owners_folders(gc: AsyncClient) -> None:
    await _login(gc)
    r = await gc.get("/v1/drive")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is True and body["service_email"] == SA
    assert {(f["id"], f["confirmed"]) for f in body["folders"]} == {
        ("root1", False),
        ("root2", False),
    }
    assert body["others"] == 1 and "stranger" not in r.text and "Free money" not in r.text


async def test_put_needs_the_csrf_header(gc: AsyncClient) -> None:
    await _login(gc)
    r = await gc.put("/v1/drive/roots/root1", json={"use": True})
    assert r.status_code == 403 and r.json()["error"] == "csrf"


async def test_use_on_and_off(gc: AsyncClient) -> None:
    await _login(gc)
    r = await gc.put("/v1/drive/roots/root1", json={"use": True}, headers=CSRF)
    assert r.status_code == 200
    assert {f["id"]: f["confirmed"] for f in r.json()["folders"]} == {"root1": True, "root2": False}
    r = await gc.put("/v1/drive/roots/root1", json={"use": False}, headers=CSRF)
    assert all(not f["confirmed"] for f in r.json()["folders"])


async def test_a_folder_shared_by_another_account_is_refused(gc: AsyncClient) -> None:
    await _login(gc)
    r = await gc.put("/v1/drive/roots/evil", json={"use": True}, headers=CSRF)
    assert r.status_code == 403
    assert r.json()["error"] == "not_offered" and "another account" in r.json()["detail"]


@pytest.mark.parametrize("body", [{}, {"use": "yes"}, {"use": 1}, {"use": True, "x": 1}])
async def test_the_body_is_strict(gc: AsyncClient, body: dict) -> None:  # type: ignore[type-arg]
    await _login(gc)
    r = await gc.put("/v1/drive/roots/root1", json=body, headers=CSRF)
    assert r.status_code == 422


async def test_a_bad_id_is_refused(gc: AsyncClient, drive: FakeDrive) -> None:
    await _login(gc)
    before = len(drive.requests)
    r = await gc.put("/v1/drive/roots/a%20b", json={"use": True}, headers=CSRF)
    assert r.status_code == 422 and len(drive.requests) == before


async def test_the_bearer_token_cannot_switch_folders_on(gc: AsyncClient) -> None:
    """No verified Google address on a script's token: it can read the list, not confirm."""
    auth = {"Authorization": "Bearer cli-token"}
    assert (await gc.get("/v1/drive", headers=auth)).status_code == 200
    r = await gc.put("/v1/drive/roots/root1", json={"use": True}, headers=auth)
    assert r.status_code == 403 and r.json()["error"] == "no_owner_email"


async def test_drive_trouble_is_a_plain_503(gc: AsyncClient, drive: FakeDrive) -> None:
    await _login(gc)
    drive.fail["list"] = 500
    r = await gc.get("/v1/drive")
    assert r.status_code == 503
    assert r.json()["error"] == "drive_unavailable" and "VENDOR" not in r.text


async def test_off_the_routes_say_not_configured(settings: Settings) -> None:
    app = create_app(settings, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/v1/drive")
            assert r.status_code == 200 and r.json() == {"configured": False}
            r = await c.put("/v1/drive/roots/root1", json={"use": True}, headers=CSRF)
            assert r.status_code == 404 and r.json()["error"] == "drive_off"


def test_the_setting_switches_drive_on(settings: Settings) -> None:
    assert drive_configured(settings) is False
    on = settings.model_copy(update={"drive": True})
    assert drive_configured(on) is True
    assert build_drive_service(settings, MemoryDocs()) is None
    assert build_drive_service(on, MemoryDocs()) is not None


def test_the_env_var_is_jarvis_drive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_DRIVE", "on")
    assert Settings(_env_file=None).drive is True  # type: ignore[call-arg]
    monkeypatch.setenv("JARVIS_DRIVE", "off")
    assert Settings(_env_file=None).drive is False  # type: ignore[call-arg]


async def test_the_app_registers_the_drive_tools_only_when_on(
    gsettings: Settings, settings: Settings, drive: FakeDrive
) -> None:
    async for c in _client(gsettings, drive):
        names = {s.name for s in c.app.state.gateway.registry.specs()}  # type: ignore[attr-defined]
        assert {"drive_folders", "drive_list", "drive_search", "drive_read"} <= names
    app = create_app(settings, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        names = {s.name for s in app.state.gateway.registry.specs()}
        assert not any(n.startswith("drive_") for n in names)
