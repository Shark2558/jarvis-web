# tests/test_r14_d_auth.py -- R14 D13 (1), as the Workshop decided after reading Google's own page
# (Sign in with Google, "security bundle"): Google puts `auth_time` in the ID token only when the
# app is published and verified, "Session age claims" is switched on in Google Auth Platform, and
# the request asks for it with the `claims` parameter; `max_age` alone is not documented to.
# So `/auth/login?reauth=1` keeps `max_age=0` AND asks for `auth_time` as essential (never
# `prompt=login`, not one of Google's documented values). A present `auth_time` is checked strictly
# (older than the start or in the future: stale). A missing one is stale ONLY when the owner's
# setting `reauth_requires_auth_time` is on (default off: the moment the re-sign-in completed, as
# before R14). The log says which (`auth_time_missing` / `auth_time_old` / `auth_time_future`),
# never the token.
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

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
WANTED = {"id_token": {"auth_time": {"essential": True}}}
REQUIRE = "reauth_requires_auth_time"


async def _client(
    settings: Settings, provider: MockProvider, gateway: Gateway, **extra: Any
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
            **extra,
        }
    )
    app = create_app(s, provider=provider, store=InMemorySessionStore(), gateway=gateway)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as c:
            c.app = app  # type: ignore[attr-defined]
            yield c


@pytest.fixture
async def gclient(
    settings: Settings, provider: MockProvider, gateway: Gateway
) -> AsyncIterator[AsyncClient]:
    async for c in _client(settings, provider, gateway):
        yield c


@pytest.fixture
async def strict(
    settings: Settings, provider: MockProvider, gateway: Gateway
) -> AsyncIterator[AsyncClient]:
    """The owner switched `reauth_requires_auth_time` on (after Google's Session age claims)."""
    async for c in _client(settings, provider, gateway, **{REQUIRE: True}):
        yield c


@pytest.fixture(params=[False, True], ids=["setting_off", "setting_on"])
async def either(
    request: pytest.FixtureRequest, settings: Settings, provider: MockProvider, gateway: Gateway
) -> AsyncIterator[AsyncClient]:
    async for c in _client(settings, provider, gateway, **{REQUIRE: request.param}):
        yield c


def _query(location: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(location).query)


async def _reauth(c: AsyncClient, **claims: Any) -> Any:
    async def fake(request: Any) -> dict[str, Any]:
        return {"userinfo": {"email": OWNER, "email_verified": True, "sub": "1", **claims}}

    c.app.state.oauth.google.authorize_access_token = fake  # type: ignore[attr-defined]
    start = await c.get("/auth/login?reauth=1", follow_redirects=False)
    assert _query(start.headers["location"])["max_age"] == ["0"]
    return await c.get("/auth/callback?code=abc&state=s")


async def _fresh_s(c: AsyncClient) -> int:
    return int((await c.get("/v1/permissions")).json()["fresh_sign_in_s"])


# ---- what /auth/login asks Google for ---------------------------------------------------------


async def test_a_re_sign_in_asks_for_auth_time_as_essential(gclient: AsyncClient) -> None:
    q = _query(
        (await gclient.get("/auth/login?reauth=1", follow_redirects=False)).headers["location"]
    )
    assert q["max_age"] == ["0"]
    assert json.loads(q["claims"][0]) == WANTED
    assert q["prompt"] == ["select_account"]  # never prompt=login: not a value Google documents


async def test_an_ordinary_sign_in_asks_for_neither(gclient: AsyncClient) -> None:
    q = _query((await gclient.get("/auth/login", follow_redirects=False)).headers["location"])
    assert "claims" not in q and "max_age" not in q


# ---- the check itself -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "claims", [{}, {"auth_time": None}, {"auth_time": "now"}, {"auth_time": True}]
)
def test_a_missing_auth_time_is_the_old_way_unless_the_setting_asks(claims: dict[str, Any]) -> None:
    assert auth_mod._reauth_at(claims, T0 - 5, T0) == (T0, auth_mod.AUTH_TIME_MISSING)
    strict = auth_mod._reauth_at(claims, T0 - 5, T0, require_auth_time=True)
    assert strict == (None, auth_mod.AUTH_TIME_MISSING)


@pytest.mark.parametrize("require", [False, True])
def test_a_present_auth_time_is_checked_strictly_either_way(require: bool) -> None:
    def at(value: float) -> tuple[float | None, str]:
        return auth_mod._reauth_at({"auth_time": value}, T0 - 5, T0, require_auth_time=require)

    assert at(int(T0 - 2)) == (T0 - 2, "")
    assert at(T0 + 30) == (T0, "")  # our clock, skew held
    assert at(T0 - 3600) == (None, auth_mod.AUTH_TIME_OLD)
    assert at(T0 + 3600) == (None, auth_mod.AUTH_TIME_FUTURE)


def test_the_setting_is_read_strictly(settings: Settings) -> None:
    assert auth_mod.requires_auth_time(settings) is False  # I1 adds the field, default False
    on = settings.model_copy(update={REQUIRE: True})
    assert auth_mod.requires_auth_time(on) is True
    assert auth_mod.requires_auth_time(settings.model_copy(update={REQUIRE: "yes"})) is False


# ---- through the real routes --------------------------------------------------------------------


async def test_without_auth_time_and_the_setting_off_it_counts_as_before(
    gclient: AsyncClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(auth_mod, "_now", lambda: T0)
    with caplog.at_level(logging.INFO, logger=auth_mod.__name__):
        r = await _reauth(gclient)  # Google left `auth_time` out (Session age claims off)
    assert r.headers["location"] == "/?reauth=done"
    assert await _fresh_s(gclient) == auth_mod.FRESH_SIGN_IN_S
    [done] = [x for x in caplog.records if x.getMessage() == "owner signed in again"]
    assert getattr(done, "auth_time", None) == "missing"


async def test_without_auth_time_and_the_setting_on_it_is_stale(
    strict: AsyncClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(auth_mod, "_now", lambda: T0)
    with caplog.at_level(logging.INFO, logger=auth_mod.__name__):
        r = await _reauth(strict)
    assert r.headers["location"] == "/?reauth=stale"
    assert await _fresh_s(strict) == 0
    [refused] = [x for x in caplog.records if x.levelno == logging.WARNING]
    assert getattr(refused, "reason", None) == auth_mod.AUTH_TIME_MISSING


async def test_an_old_auth_time_is_stale_and_logged_as_old(
    either: AsyncClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    c = either
    monkeypatch.setattr(auth_mod, "_now", lambda: T0)
    with caplog.at_level(logging.INFO, logger=auth_mod.__name__):
        r = await _reauth(c, auth_time=int(T0 - 3600))  # Google did not ask again
    assert r.headers["location"] == "/?reauth=stale"
    assert await _fresh_s(c) == 0
    [refused] = [x for x in caplog.records if x.levelno == logging.WARNING]
    assert getattr(refused, "reason", None) == auth_mod.AUTH_TIME_OLD
    logged = " ".join(f"{x.getMessage()} {x.__dict__}" for x in caplog.records)
    assert OWNER not in logged and str(int(T0 - 3600)) not in logged  # the kind only


async def test_a_fresh_auth_time_opens_the_window(
    either: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = either
    monkeypatch.setattr(auth_mod, "_now", lambda: T0)
    r = await _reauth(c, auth_time=int(T0))
    assert r.headers["location"] == "/?reauth=done"
    assert await _fresh_s(c) == auth_mod.FRESH_SIGN_IN_S
