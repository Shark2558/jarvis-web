# tests/test_web_auth.py — web console shell, Google sign-in, allowlist, CSRF, rate limit
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.api import create_app
from jarvis.config import AuthMode, Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore

OWNER = "akash@example.com"
CSRF = {"X-Requested-With": "JARVIS"}


@pytest.fixture
def google_settings(settings: Settings) -> Settings:
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


@pytest.fixture
async def gclient(google_settings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(google_settings, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            c.app = app  # type: ignore[attr-defined]
            yield c


def _fake_google(app: Any, email: str, email_verified: bool = True) -> None:
    """Replace the network half of the OIDC exchange: Google said this is who the user is."""

    async def fake_authorize_access_token(request: Any) -> dict[str, Any]:
        return {"userinfo": {"email": email, "email_verified": email_verified, "sub": "123"}}

    app.state.oauth.google.authorize_access_token = fake_authorize_access_token


async def _login(c: AsyncClient, email: str, verified: bool = True) -> Any:
    _fake_google(c.app, email, verified)  # type: ignore[attr-defined]
    return await c.get("/auth/callback?code=abc&state=whatever")


# ---- console shell --------------------------------------------------------------------------


async def test_console_shell_is_served(client: AsyncClient, gclient: AsyncClient) -> None:
    for c in (client, gclient):
        r = await c.get("/")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        assert "JARVIS" in r.text


# ---- google sign-in -------------------------------------------------------------------------


async def test_login_redirects_to_google_with_state(gclient: AsyncClient) -> None:
    r = await gclient.get("/auth/login", follow_redirects=False)
    assert r.status_code in (302, 307)
    loc = r.headers["location"]
    assert loc.startswith("https://accounts.google.com/")
    assert "state=" in loc and "client_id=cid.apps.googleusercontent.com" in loc
    assert "redirect_uri=http%3A%2F%2Ftest%2Fauth%2Fcallback" in loc


async def test_owner_signs_in_and_cookie_authorizes_api(gclient: AsyncClient) -> None:
    assert (await gclient.get("/auth/me")).status_code == 401
    assert (await gclient.post("/v1/chat", json={"message": "hi"}, headers=CSRF)).status_code == 401

    r = await _login(gclient, OWNER)
    assert r.status_code in (302, 307) and r.headers["location"] == "/"
    set_cookie = r.headers.get("set-cookie", "")
    assert "httponly" in set_cookie.lower() and "samesite=lax" in set_cookie.lower()

    me = await gclient.get("/auth/me")
    assert me.status_code == 200 and me.json()["email"] == OWNER

    ok = await gclient.post("/v1/chat", json={"message": "hi"}, headers=CSRF)
    assert ok.status_code == 200 and ok.json()["reply"]


async def test_non_owner_is_refused_without_cookie(gclient: AsyncClient) -> None:
    r = await _login(gclient, "stranger@example.com")
    assert r.status_code == 403
    assert "set-cookie" not in r.headers or "jarvis_session=;" in r.headers.get("set-cookie", "")
    assert (await gclient.get("/auth/me")).status_code == 401


async def test_unverified_email_is_refused(gclient: AsyncClient) -> None:
    r = await _login(gclient, OWNER, verified=False)
    assert r.status_code == 403
    assert (await gclient.get("/auth/me")).status_code == 401


async def test_cookie_auth_requires_csrf_header_on_writes(gclient: AsyncClient) -> None:
    await _login(gclient, OWNER)
    # reads are fine without the header
    assert (await gclient.get("/v1/sessions")).status_code == 200
    # writes are not
    r = await gclient.post("/v1/chat", json={"message": "hi"})
    assert r.status_code == 403 and r.json()["error"] == "csrf"
    assert (await gclient.post("/v1/chat", json={"message": "hi"}, headers=CSRF)).status_code == 200


async def test_logout_clears_session(gclient: AsyncClient) -> None:
    await _login(gclient, OWNER)
    assert (await gclient.get("/auth/me")).status_code == 200
    r = await gclient.post("/auth/logout", headers=CSRF, follow_redirects=False)
    assert r.status_code in (200, 302, 303)
    assert (await gclient.get("/auth/me")).status_code == 401


async def test_bearer_token_still_works_in_google_mode(gclient: AsyncClient) -> None:
    hdr = {"Authorization": "Bearer cli-token"}
    assert (await gclient.post("/v1/chat", json={"message": "hi"}, headers=hdr)).status_code == 200
    bad = {"Authorization": "Bearer nope"}
    assert (await gclient.post("/v1/chat", json={"message": "hi"}, headers=bad)).status_code == 401


async def test_token_mode_has_no_google_routes(client: AsyncClient) -> None:
    assert (await client.get("/auth/login")).status_code == 404
    assert (await client.get("/auth/me")).status_code == 401


# ---- settings invariants --------------------------------------------------------------------


def test_google_mode_invariants(settings: Settings) -> None:
    base = settings.model_copy(
        update={"env": "prod", "api_token": SecretStr("t"), "auth_mode": AuthMode.GOOGLE}
    )
    with pytest.raises(RuntimeError, match="GOOGLE_CLIENT_ID"):
        base.require_prod_invariants()
    s2 = base.model_copy(
        update={
            "google_client_id": "cid",
            "google_client_secret": SecretStr("s"),
            "session_secret": SecretStr("y" * 32),
            "public_base_url": "https://j.example",
        }
    )
    with pytest.raises(RuntimeError, match="OWNER_EMAILS"):
        s2.require_prod_invariants()
    s3 = s2.model_copy(update={"owner_emails": ["a@b.c"], "session_secret": SecretStr("short")})
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        s3.require_prod_invariants()


def test_owner_emails_parse_from_csv_and_normalise() -> None:
    s = Settings(_env_file=None, owner_emails="  A@B.com, c@d.org ")  # type: ignore[arg-type]
    assert s.owner_emails == ["a@b.com", "c@d.org"]


# ---- rate limit -----------------------------------------------------------------------------


async def test_rate_limit_returns_429(settings: Settings) -> None:
    s = settings.model_copy(update={"rate_limit_per_minute": 3})
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            codes = [(await c.get("/v1/sessions")).status_code for _ in range(5)]
            assert codes[:3] == [200, 200, 200] and 429 in codes[3:]
            last = await c.get("/v1/sessions")
            assert last.status_code == 429 and "retry-after" in last.headers
            # health is never rate limited (platform probes)
            assert (await c.get("/health")).status_code == 200


# ---- review fixes (regressions) ------------------------------------------------------------


async def test_rate_limit_key_cannot_be_spoofed_via_forwarded_for(settings: Settings) -> None:
    """Render appends the real client IP as the *last* X-Forwarded-For hop; the first entries are
    attacker-controlled. Cycling them must not mint fresh buckets."""
    s = settings.model_copy(update={"rate_limit_per_minute": 2})
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            codes = []
            for i in range(4):
                hdr = {"X-Forwarded-For": f"10.0.0.{i}, 203.0.113.9"}
                codes.append((await c.get("/v1/sessions", headers=hdr)).status_code)
            assert codes == [200, 200, 429, 429]


async def test_session_has_absolute_lifetime(gclient: AsyncClient, monkeypatch: Any) -> None:
    import jarvis.api.auth as auth_mod

    base = 1_700_000_000.0
    monkeypatch.setattr(auth_mod, "_now", lambda: base)
    await _login(gclient, OWNER)
    assert (await gclient.get("/auth/me")).status_code == 200
    # sliding refresh must NOT extend past the absolute cap
    monkeypatch.setattr(auth_mod, "_now", lambda: base + auth_mod.SESSION_ABSOLUTE_MAX_S + 1)
    assert (await gclient.get("/auth/me")).status_code == 401


async def test_hardening_headers_on_json_responses(gclient: AsyncClient) -> None:
    r = await gclient.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "max-age=" in r.headers.get("strict-transport-security", "max-age=")


async def test_console_script_is_external_and_csp_has_no_unsafe_inline_script(
    client: AsyncClient,
) -> None:
    r = await client.get("/")
    assert "'unsafe-inline'" not in r.headers["content-security-policy"].split("style-src")[0]
    assert 'src="/static/console.js"' in r.text
    js = await client.get("/static/console.js")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
