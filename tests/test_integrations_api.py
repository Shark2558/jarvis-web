# tests/test_integrations_api.py — slice 6: /connect/google flow, /v1/integrations, wiring
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.api import create_app
from jarvis.api.identity import user_id_for_email
from jarvis.config import AuthMode, SessionBackend, Settings
from jarvis.integrations.google import REVOKE_URL, TOOL_SCOPES
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage import build_storage
from jarvis.tools.setup import build_gateway

OWNER = "akash@example.com"
OTHER = "partner@example.com"
CSRF = {"X-Requested-With": "JARVIS"}
KEY_B64 = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="


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


async def _client(app: Any) -> AsyncClient:
    c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    c.app = app  # type: ignore[attr-defined]
    return c


async def _login(c: AsyncClient, email: str) -> None:
    async def fake(request: Any) -> dict[str, Any]:
        return {"userinfo": {"email": email, "email_verified": True, "sub": email}}

    c.app.state.oauth.google.authorize_access_token = fake  # type: ignore[attr-defined]
    r = await c.get("/auth/callback?code=abc&state=x")
    assert r.status_code in (302, 307)


def _fake_consent(c: AsyncClient, email: str, *, refresh: bool = True) -> None:
    """Google's half of the tools consent: who consented, which tokens came back."""

    async def fake(request: Any) -> dict[str, Any]:
        tok: dict[str, Any] = {
            "access_token": "ya29.new",
            "expires_at": 1_900_000_000,
            "scope": " ".join(TOOL_SCOPES),
            "userinfo": {"email": email, "email_verified": True, "sub": "1"},
        }
        if refresh:
            tok["refresh_token"] = "1//refresh"
        return tok

    c.app.state.oauth.google_tools.authorize_access_token = fake  # type: ignore[attr-defined]


@pytest.fixture
async def gc(gsettings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(gsettings, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        c = await _client(app)
        try:
            yield c
        finally:
            await c.aclose()


# ---- wiring ---------------------------------------------------------------------------------


async def test_google_mode_registers_google_tools_and_drops_fake_twins(gc: AsyncClient) -> None:
    names = {s.name for s in gc.app.state.gateway.registry.specs()}  # type: ignore[attr-defined]
    assert {"calendar_list_events", "gmail_send", "gmail_search", "calendar_delete_event"} <= names
    assert "get_calendar" not in names and "send_message" not in names
    assert {"list_tasks", "create_reminder"} <= names  # harmless dev builtins stay


async def test_token_mode_has_no_google_tools_or_routes(client: AsyncClient) -> None:
    assert (await client.get("/v1/integrations")).status_code == 404
    assert (await client.get("/connect/google")).status_code == 404


def test_build_gateway_without_connector_keeps_builtins(settings: Settings) -> None:
    names = {s.name for s in build_gateway(settings).registry.specs()}
    assert "get_calendar" in names and "gmail_send" not in names


def test_build_storage_wires_a_token_store(gsettings: Settings) -> None:
    from jarvis.integrations.vault import MemoryTokenStore

    st = build_storage(gsettings.model_copy(update={"session_backend": SessionBackend.MEMORY}))
    assert isinstance(st.tokens, MemoryTokenStore)


def test_tools_disabled_flag_keeps_google_out(gsettings: Settings) -> None:
    from jarvis.integrations.google import build_google_connector
    from jarvis.integrations.vault import MemoryTokenStore

    off = gsettings.model_copy(update={"google_tools_enabled": False})
    assert build_google_connector(off, MemoryTokenStore()) is None
    assert build_google_connector(gsettings, MemoryTokenStore()) is not None


# ---- connect --------------------------------------------------------------------------------


async def test_connect_requires_a_signed_in_owner(gc: AsyncClient) -> None:
    assert (await gc.get("/connect/google", follow_redirects=False)).status_code == 401
    # a bearer token is not a browser: no OAuth dance for scripts
    r = await gc.get(
        "/connect/google", headers={"Authorization": "Bearer cli-token"}, follow_redirects=False
    )
    assert r.status_code == 401


async def test_connect_redirects_to_google_with_offline_consent_and_login_hint(
    gc: AsyncClient,
) -> None:
    await _login(gc, OWNER)
    r = await gc.get("/connect/google", follow_redirects=False)
    assert r.status_code in (302, 307)
    url = urlsplit(r.headers["location"])
    assert url.netloc == "accounts.google.com"
    q = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert q["access_type"] == "offline" and q["prompt"] == "consent"
    assert q["include_granted_scopes"] == "true" and q["login_hint"] == OWNER
    assert q["code_challenge_method"] == "S256" and q["code_challenge"] and q["state"]
    assert q["redirect_uri"] == "http://test/connect/google/callback"
    scopes = set(q["scope"].split())
    assert {
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/gmail.send",
        "openid",
        "email",
    } <= scopes


async def test_callback_links_the_owner_and_redirects_to_console(gc: AsyncClient) -> None:
    await _login(gc, OWNER)
    await gc.get("/connect/google", follow_redirects=False)
    _fake_consent(gc, OWNER)
    r = await gc.get("/connect/google/callback?code=c&state=s", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/?connected=google"
    st = (await gc.get("/v1/integrations")).json()["google"]
    assert st["connected"] is True and st["email"] == OWNER and st["needs_reconnect"] is False
    assert "https://www.googleapis.com/auth/gmail.send" in st["scopes"]
    assert st["expires_at"] == 1_900_000_000
    assert "ya29" not in r.text and "refresh" not in str(st)
    saved = await gc.app.state.google.store.get(user_id_for_email(OWNER))  # type: ignore[attr-defined]
    assert saved is not None and saved.refresh_token.get_secret_value() == "1//refresh"


async def test_callback_refuses_a_different_google_account(gc: AsyncClient) -> None:
    await _login(gc, OWNER)
    await gc.get("/connect/google", follow_redirects=False)
    _fake_consent(gc, "someone.else@example.com")
    r = await gc.get("/connect/google/callback?code=c&state=s", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/?connect_error=wrong_account"
    assert (await gc.get("/v1/integrations")).json()["google"]["connected"] is False


async def test_callback_refuses_when_not_started_by_this_owner(gc: AsyncClient) -> None:
    await _login(gc, OWNER)
    _fake_consent(gc, OWNER)
    r = await gc.get("/connect/google/callback?code=c&state=s", follow_redirects=False)
    assert r.headers["location"] == "/?connect_error=not_started"  # no connect started here
    # started as OWNER, but the browser is now signed in as OTHER
    await gc.get("/connect/google", follow_redirects=False)
    await _login(gc, OTHER)
    _fake_consent(gc, OTHER)
    r2 = await gc.get("/connect/google/callback?code=c&state=s", follow_redirects=False)
    assert r2.status_code == 302 and r2.headers["location"] == "/?connect_error=not_started"
    for who in (OWNER, OTHER):
        assert await gc.app.state.google.store.get(user_id_for_email(who)) is None  # type: ignore[attr-defined]


async def test_callback_without_signin_is_unauthorised(gc: AsyncClient) -> None:
    _fake_consent(gc, OWNER)
    r = await gc.get("/connect/google/callback?code=c&state=s", follow_redirects=False)
    assert r.status_code == 401


async def test_callback_without_refresh_token_is_refused(gc: AsyncClient) -> None:
    await _login(gc, OWNER)
    await gc.get("/connect/google", follow_redirects=False)
    _fake_consent(gc, OWNER, refresh=False)
    r = await gc.get("/connect/google/callback?code=c&state=s", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/?connect_error=no_refresh_token"
    assert (await gc.get("/v1/integrations")).json()["google"]["connected"] is False


async def test_callback_hides_authlib_errors(gc: AsyncClient) -> None:
    await _login(gc, OWNER)
    await gc.get("/connect/google", follow_redirects=False)

    async def boom(request: Any) -> dict[str, Any]:
        raise RuntimeError("mismatching_state: CSRF Warning! secret-detail")

    gc.app.state.oauth.google_tools.authorize_access_token = boom  # type: ignore[attr-defined]
    r = await gc.get("/connect/google/callback?code=c&state=s", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/?connect_error=oauth_failed"
    assert "secret-detail" not in r.text


# ---- status + disconnect --------------------------------------------------------------------


async def test_status_requires_auth_and_is_per_user(gc: AsyncClient) -> None:
    assert (await gc.get("/v1/integrations")).status_code == 401
    await _login(gc, OWNER)
    assert (await gc.get("/v1/integrations")).json() == {
        "google": {
            "connected": False,
            "email": None,
            "scopes": [],
            "expires_at": None,
            "needs_reconnect": False,
        }
    }
    # bearer token = primary owner (OWNER is first in the list)
    r = await gc.get("/v1/integrations", headers={"Authorization": "Bearer cli-token"})
    assert r.status_code == 200 and r.json()["google"]["connected"] is False


async def test_disconnect_needs_csrf_header_then_revokes_and_forgets(gc: AsyncClient) -> None:
    await _login(gc, OWNER)
    await gc.get("/connect/google", follow_redirects=False)
    _fake_consent(gc, OWNER)
    await gc.get("/connect/google/callback?code=c&state=s", follow_redirects=False)
    revoked: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        revoked.append(req)
        return httpx.Response(200)

    gc.app.state.google.http = httpx.AsyncClient(  # type: ignore[attr-defined]
        transport=httpx.MockTransport(handler)
    )
    assert (await gc.post("/v1/integrations/google/disconnect", json={})).status_code == 403
    r = await gc.post("/v1/integrations/google/disconnect", json={}, headers=CSRF)  # console body
    assert r.status_code == 200 and r.json() == {"ok": True, "google": {"connected": False}}
    assert len(revoked) == 1 and str(revoked[0].url) == REVOKE_URL
    assert (await gc.get("/v1/integrations")).json()["google"]["connected"] is False
    # idempotent
    assert (await gc.post("/v1/integrations/google/disconnect", headers=CSRF)).status_code == 200
    assert len(revoked) == 1


async def test_second_owner_does_not_see_the_first_owners_link(gc: AsyncClient) -> None:
    await _login(gc, OWNER)
    await gc.get("/connect/google", follow_redirects=False)
    _fake_consent(gc, OWNER)
    await gc.get("/connect/google/callback?code=c&state=s", follow_redirects=False)
    await _login(gc, OTHER)
    assert (await gc.get("/v1/integrations")).json()["google"]["connected"] is False
