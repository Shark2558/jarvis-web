# tests/test_r14_d_auth.py -- R14 D13 (1): a re-sign-in whose ID token carries no `auth_time` is
# NOT fresh. OpenID Connect: when `max_age` is sent (`/auth/login?reauth=1` sends `max_age=0`),
# `auth_time` must come back, so refusing without it is safe; before R14 a missing `auth_time`
# counted as "now" and opened the 5-minute passkey window on Google's silence.
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from jarvis.api import auth as auth_mod
from jarvis.api import create_app
from jarvis.config import AuthMode, Settings
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.tools import Gateway

ORIGIN = "http://test"
OWNER = "owner@example.com"
T0 = 1_800_000_000.0


@pytest.fixture
async def gclient(
    settings: Settings, provider: MockProvider, gateway: Gateway
) -> AsyncIterator[AsyncClient]:
    s = settings.model_copy(
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
    app = create_app(s, provider=provider, store=InMemorySessionStore(), gateway=gateway)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as c:
            c.app = app  # type: ignore[attr-defined]
            yield c


async def _reauth(c: AsyncClient, **claims: Any) -> Any:
    async def fake(request: Any) -> dict[str, Any]:
        return {"userinfo": {"email": OWNER, "email_verified": True, "sub": "1", **claims}}

    c.app.state.oauth.google.authorize_access_token = fake  # type: ignore[attr-defined]
    start = await c.get("/auth/login?reauth=1", follow_redirects=False)
    assert "max_age=0" in start.headers["location"]
    return await c.get("/auth/callback?code=abc&state=s")


async def _fresh_s(c: AsyncClient) -> int:
    return int((await c.get("/v1/permissions")).json()["fresh_sign_in_s"])


@pytest.mark.parametrize("claims", [{}, {"auth_time": None}, {"auth_time": "now"}])
def test_a_missing_or_malformed_auth_time_is_not_a_fresh_sign_in(claims: dict[str, Any]) -> None:
    assert auth_mod._reauth_at(claims, T0 - 5, T0) is None


def test_a_bool_auth_time_is_malformed_too() -> None:
    assert auth_mod._reauth_at({"auth_time": True}, T0 - 5, T0) is None


def test_an_auth_time_inside_the_re_sign_in_counts() -> None:
    assert auth_mod._reauth_at({"auth_time": int(T0 - 2)}, T0 - 5, T0) == T0 - 2
    assert auth_mod._reauth_at({"auth_time": T0 + 30}, T0 - 5, T0) == T0  # our clock, skew held


async def test_google_without_auth_time_is_stale_and_stamps_nothing(
    gclient: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth_mod, "_now", lambda: T0)
    r = await _reauth(gclient)  # Google left `auth_time` out
    assert r.headers["location"] == "/?reauth=stale"
    assert await _fresh_s(gclient) == 0


async def test_google_with_a_fresh_auth_time_opens_the_window(
    gclient: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth_mod, "_now", lambda: T0)
    r = await _reauth(gclient, auth_time=int(T0))
    assert r.headers["location"] == "/?reauth=done"
    assert await _fresh_s(gclient) == auth_mod.FRESH_SIGN_IN_S
