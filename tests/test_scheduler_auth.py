# tests/test_scheduler_auth.py — slice 7: Google OIDC for POST /internal/brief/tick
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from joserfc import jwt
from joserfc.jwk import RSAKey
from pydantic import SecretStr

from jarvis.api import create_app
from jarvis.api.scheduler_auth import TICK_PATH, GoogleOIDCVerifier
from jarvis.config import AuthMode, Settings
from jarvis.integrations.google import JWKS_URL
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore

NOW = 1_800_000_000
SA = "jarvis-scheduler@proj.iam.gserviceaccount.com"
AUD = "http://test" + TICK_PATH
KEY = RSAKey.generate_key(2048, parameters={"kid": "k1"})
OTHER_KEY = RSAKey.generate_key(2048, parameters={"kid": "k1"})  # same kid, wrong key


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def claims(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "iss": "https://accounts.google.com",
        "aud": AUD,
        "email": SA,
        "email_verified": True,
        "iat": NOW - 10,
        "exp": NOW + 3590,
        "sub": "1234",
        "azp": "1234",
    }
    base.update(over)
    return {k: v for k, v in base.items() if v is not None}


def token(key: RSAKey = KEY, kid: str = "k1", **over: Any) -> str:
    return jwt.encode({"alg": "RS256", "kid": kid}, claims(**over), key)


class FakeJWKS:
    def __init__(self, *keys: RSAKey) -> None:
        self.keys = list(keys)
        self.fetches = 0
        self.down = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert str(request.url) == JWKS_URL
        self.fetches += 1
        if self.down:
            return httpx.Response(503)
        body = {
            "keys": [k.as_dict(private=False) | {"use": "sig", "alg": "RS256"} for k in self.keys]
        }
        return httpx.Response(200, json=body, headers={"Cache-Control": "public, max-age=20000"})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


class Clock:
    def __init__(self) -> None:
        self.t = float(NOW)

    def __call__(self) -> float:
        return self.t


def verifier(jwks: FakeJWKS, clock: Clock | None = None) -> GoogleOIDCVerifier:
    return GoogleOIDCVerifier(audience=AUD, email=SA, http=jwks.client(), now=clock or Clock())


# ---- the verifier ------------------------------------------------------------------------------


async def test_a_valid_google_token_passes_and_jwks_is_cached() -> None:
    jwks = FakeJWKS(KEY)
    v = verifier(jwks)
    assert await v.verify(token()) is True
    assert await v.verify(token(iss="accounts.google.com", email=SA.upper())) is True
    assert jwks.fetches == 1


@pytest.mark.parametrize(
    "over",
    [
        {"aud": "http://test/v1/chat"},
        {"aud": [AUD]},
        {"iss": "https://evil.example"},
        {"email": "someone@proj.iam.gserviceaccount.com"},
        {"email_verified": False},
        {"email_verified": "true"},
        {"email_verified": None},
        {"exp": NOW - 61},
        {"exp": None},
        {"iat": NOW + 61},
        {"iat": None},
        {"exp": "4102444800"},
    ],
)
async def test_bad_claims_are_refused(over: dict[str, Any]) -> None:
    assert await verifier(FakeJWKS(KEY)).verify(token(**over)) is False


async def test_skew_is_sixty_seconds() -> None:
    v = verifier(FakeJWKS(KEY))
    assert await v.verify(token(exp=NOW - 59)) is True
    assert await v.verify(token(iat=NOW + 59)) is True


async def test_wrong_signing_key_and_tampering_are_refused() -> None:
    v = verifier(FakeJWKS(KEY))
    assert await v.verify(token(key=OTHER_KEY)) is False
    h, p, s = token().split(".")
    forged = _b64(json.dumps(claims(email="x@evil.example")).encode())
    assert await v.verify(f"{h}.{forged}.{s}") is False


async def test_alg_none_is_refused() -> None:
    h = _b64(json.dumps({"alg": "none", "kid": "k1"}).encode())
    p = _b64(json.dumps(claims()).encode())
    v = verifier(FakeJWKS(KEY))
    assert await v.verify(f"{h}.{p}.") is False
    assert await v.verify(f"{h}.{p}") is False


async def test_hs256_signed_with_the_public_key_is_refused() -> None:
    """Classic algorithm confusion: HMAC keyed with the (public) RSA key material."""
    pub = KEY.as_pem(private=False)
    v = verifier(FakeJWKS(KEY))
    for secret in (pub, json.dumps(KEY.as_dict(private=False)).encode()):
        h = _b64(json.dumps({"alg": "HS256", "kid": "k1", "typ": "JWT"}).encode())
        p = _b64(json.dumps(claims()).encode())
        sig = hmac.new(secret, f"{h}.{p}".encode(), hashlib.sha256).digest()
        assert await v.verify(f"{h}.{p}.{_b64(sig)}") is False


@pytest.mark.parametrize("raw", ["", "abc", "a.b.c", "x" * 5000, "...", "e30.e30.e30"])
async def test_garbage_is_refused(raw: str) -> None:
    assert await verifier(FakeJWKS(KEY)).verify(raw) is False


async def test_unknown_kid_refetches_at_most_once_a_minute() -> None:
    rotated = RSAKey.generate_key(2048, parameters={"kid": "k2"})
    jwks, clock = FakeJWKS(KEY), Clock()
    v = verifier(jwks, clock)
    assert await v.verify(token()) is True
    jwks.keys.append(rotated)  # Google rotated keys
    clock.t += 30
    assert await v.verify(token(key=rotated, kid="k2", iat=int(clock.t))) is False  # too soon
    clock.t += 31
    assert await v.verify(token(key=rotated, kid="k2", iat=int(clock.t))) is True
    assert jwks.fetches == 2
    for _ in range(5):  # a flood of unknown kids never hammers Google
        await v.verify(token(kid="nope", iat=int(clock.t)))
    assert jwks.fetches == 2


async def test_jwks_outage_fails_closed() -> None:
    jwks = FakeJWKS(KEY)
    jwks.down = True
    assert await verifier(jwks).verify(token()) is False


# ---- the route ------------------------------------------------------------------------------


@pytest.fixture
def ssettings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "brief_scheduler_sa": SA,
            "public_base_url": "http://test",
            "api_token": SecretStr("cli-token"),
        }
    )


async def _app_client(s: Settings, jwks: FakeJWKS | None) -> AsyncIterator[AsyncClient]:
    v = verifier(jwks) if jwks is not None else None
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore(), scheduler_verifier=v)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            c.app = app  # type: ignore[attr-defined]
            yield c


@pytest.fixture
async def sc(ssettings: Settings) -> AsyncIterator[AsyncClient]:
    async for c in _app_client(ssettings, FakeJWKS(KEY)):
        yield c


async def test_tick_with_a_scheduler_token_runs(sc: AsyncClient) -> None:
    r = await sc.post(TICK_PATH, headers={"Authorization": f"Bearer {token()}"})
    assert r.status_code == 200
    assert r.json() == {"checked": 1, "generated": r.json()["generated"], "delivered": 0}
    assert set(r.json()) == {"checked", "generated", "delivered"}


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer cli-token"},  # the API token is NOT accepted here
        {"Authorization": "Basic Y2xpLXRva2Vu"},
        {"Authorization": f"bearer  {token(aud='http://test/other')}"},
        {"Authorization": f"Bearer {token(email='other@x.iam.gserviceaccount.com')}"},
    ],
)
async def test_tick_refuses_everything_else_with_a_bare_401(
    sc: AsyncClient, headers: dict[str, str]
) -> None:
    r = await sc.post(TICK_PATH, headers=headers)
    assert r.status_code == 401 and r.content == b""


async def test_tick_route_is_absent_without_a_scheduler_account(settings: Settings) -> None:
    async for c in _app_client(settings, None):
        assert (
            await c.post(TICK_PATH, headers={"Authorization": f"Bearer {token()}"})
        ).status_code == 404


async def test_a_signed_in_browser_cookie_cannot_tick(ssettings: Settings) -> None:
    gs = ssettings.model_copy(
        update={
            "auth_mode": AuthMode.GOOGLE,
            "google_client_id": "cid",
            "google_client_secret": SecretStr("gsecret"),
            "owner_emails": ["akash@example.com"],
            "session_secret": SecretStr("x" * 32),
        }
    )
    async for c in _app_client(gs, FakeJWKS(KEY)):

        async def fake(request: Any) -> dict[str, Any]:
            return {"userinfo": {"email": "akash@example.com", "email_verified": True}}

        c.app.state.oauth.google.authorize_access_token = fake  # type: ignore[attr-defined]
        await c.get("/auth/callback?code=a&state=b")
        assert (await c.get("/v1/brief/today")).status_code == 200  # the cookie works on /v1
        r = await c.post(TICK_PATH, headers={"X-Requested-With": "JARVIS"})
        assert r.status_code == 401 and r.content == b""


async def test_tick_is_rate_limited(ssettings: Settings) -> None:
    s = ssettings.model_copy(update={"rate_limit_per_minute": 2})
    async for c in _app_client(s, FakeJWKS(KEY)):
        codes = [(await c.post(TICK_PATH)).status_code for _ in range(3)]
        assert codes == [401, 401, 429]
