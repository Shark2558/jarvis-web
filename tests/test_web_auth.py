# tests/test_web_auth.py — web console shell, Google sign-in, allowlist, CSRF, rate limit
from __future__ import annotations

import base64
import os
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


def _prod_google(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "env": "prod",
            "api_token": SecretStr("t"),
            "auth_mode": AuthMode.GOOGLE,
            "google_client_id": "cid",
            "google_client_secret": SecretStr("s"),
            "session_secret": SecretStr("y" * 32),
            "public_base_url": "https://j.example",
            "owner_emails": ["a@b.c"],
        }
    )


def test_missing_token_key_outside_dev_turns_google_tools_off_not_the_app(
    settings: Settings,
) -> None:
    """Rollout: an auto-deploy keeps the old secrets, so the first slice-6 revision has no
    JARVIS_TOKEN_KEY. It must start (health check) with the Google tools off."""
    from jarvis.integrations.google import google_tools_configured

    base = _prod_google(settings)
    base.require_prod_invariants()  # no longer a start-up error
    assert google_tools_configured(base) is False
    with pytest.raises(RuntimeError, match="TOKEN_KEY is invalid"):  # present but bad: still fatal
        base.model_copy(update={"token_key": SecretStr("too-short")}).require_prod_invariants()
    with pytest.raises(RuntimeError, match="weak"):  # 32 zero bytes: valid base64, no entropy
        base.model_copy(update={"token_key": SecretStr("A" * 43 + "=")}).require_prod_invariants()
    key = SecretStr(base64.b64encode(os.urandom(32)).decode())
    ok = base.model_copy(update={"token_key": key})
    ok.require_prod_invariants()
    assert len(ok.token_key_bytes() or b"") == 32 and google_tools_configured(ok) is True
    # dev keeps working without a key (tokens in memory)
    dev = base.model_copy(update={"env": "dev"})
    assert google_tools_configured(dev) is True


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


def test_owner_emails_parse_from_real_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: pydantic-settings JSON-decodes list fields read from env vars, so a plain
    'me@gmail.com' (what Cloud Run / Render pass) crashed startup. Must accept CSV."""
    monkeypatch.setenv("JARVIS_OWNER_EMAILS", "Me@Gmail.com")
    assert Settings(_env_file=None).owner_emails == ["me@gmail.com"]  # type: ignore[call-arg]
    monkeypatch.setenv("JARVIS_OWNER_EMAILS", " a@b.com , C@d.org ")
    assert Settings(_env_file=None).owner_emails == ["a@b.com", "c@d.org"]  # type: ignore[call-arg]
    monkeypatch.setenv("JARVIS_OWNER_EMAILS", '["j@k.com"]')  # JSON form still works
    assert Settings(_env_file=None).owner_emails == ["j@k.com"]  # type: ignore[call-arg]


async def test_prod_app_boots_with_cloud_run_style_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whole-app smoke test with exactly the env the deploy script sets (no provider injected)."""
    env = {
        "JARVIS_ENV": "prod",
        "JARVIS_AUTH_MODE": "google",
        "JARVIS_PUBLIC_BASE_URL": "https://jarvis-1.asia-south1.run.app",
        "JARVIS_OWNER_EMAILS": "me@gmail.com",
        "JARVIS_GOOGLE_CLIENT_ID": "cid.apps.googleusercontent.com",
        "JARVIS_GOOGLE_CLIENT_SECRET": "GOCSPX-x",
        "JARVIS_SESSION_SECRET": "z" * 40,
        "JARVIS_API_TOKEN": "t" * 30,
        "JARVIS_ANTHROPIC_API_KEY": "sk-ant-x",
        "JARVIS_SESSION_BACKEND": "memory",
        "JARVIS_LOG_JSON": "true",
        "JARVIS_TOKEN_KEY": "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",  # slice 6 vault key
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    app = create_app(Settings(_env_file=None))  # type: ignore[call-arg]
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://t") as c:
            assert (await c.get("/health")).status_code == 200
            r = await c.get("/auth/login", follow_redirects=False)
            assert r.status_code in (302, 307) and "accounts.google.com" in r.headers["location"]
            assert (await c.get("/")).status_code == 200


CLOUD_RUN_ENV = {
    "JARVIS_ENV": "prod",
    "JARVIS_AUTH_MODE": "google",
    "JARVIS_PUBLIC_BASE_URL": "https://jarvis-1.asia-south1.run.app",
    "JARVIS_OWNER_EMAILS": "me@gmail.com",
    "JARVIS_GOOGLE_CLIENT_ID": "cid.apps.googleusercontent.com",
    "JARVIS_GOOGLE_CLIENT_SECRET": "GOCSPX-x",
    "JARVIS_SESSION_SECRET": "z" * 40,
    "JARVIS_API_TOKEN": "t" * 30,
    "JARVIS_ANTHROPIC_API_KEY": "sk-ant-x",
    "JARVIS_SESSION_BACKEND": "memory",
}


@pytest.mark.parametrize("with_key", [False, True])
async def test_prod_boots_without_a_token_key_with_google_tools_off(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, with_key: bool
) -> None:
    """Rollout: the first auto-deployed slice-6 revision has the OLD secrets (no token key). It
    must pass the health check with the Google tools and routes off (the console then shows
    "Not available"), warn once, and turn them on as soon as the key is bound."""
    import jarvis.api.app as app_module

    monkeypatch.setattr(app_module, "configure_logging", lambda *a, **k: None)  # keep caplog
    for k, v in CLOUD_RUN_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("JARVIS_TOKEN_KEY", raising=False)
    if with_key:
        monkeypatch.setenv("JARVIS_TOKEN_KEY", base64.b64encode(os.urandom(32)).decode())
    caplog.set_level("WARNING")
    app = create_app(Settings(_env_file=None))  # type: ignore[call-arg]
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://t") as c:
            assert (await c.get("/health")).status_code == 200
            names = {t.name for t in app.state.gateway.registry.specs()}
            integrations = (await c.get("/v1/integrations")).status_code
            connect = (await c.get("/connect/google", follow_redirects=False)).status_code
    key_warnings = [r for r in caplog.records if "JARVIS_TOKEN_KEY" in r.getMessage()]
    if with_key:
        assert {"gmail_send", "calendar_list_events"} <= names
        assert integrations == 401 and connect == 401  # mounted, sign-in required
        assert key_warnings == []
    else:
        assert not any(n.startswith(("gmail_", "calendar_")) for n in names)
        assert integrations == 404 and connect == 404  # the console renders "Not available"
        assert len(key_warnings) == 1 and key_warnings[0].levelname == "WARNING"
