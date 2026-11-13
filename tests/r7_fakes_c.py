# tests/r7_fakes_c.py -- R7 Part C (docs/plans/r7-mobile.md D4-D6, D16, D21): the real app with
# Google sign-in (Google's half faked), the real show lock and app lock inside the session
# middleware, the real permissions with software passkeys, a movable clock for Part C
# (`app.state.phone_clock`) and a notifier that records. Imported bare by Part C's tests and by
# evals/r7/phone.py. Nothing personal: made-up owners at example.com, keys made in the test.
#
#   phone_app(settings)          the app, started, with the clock and the recording notifier
#   browser(app, ...)            a signed-in browser (a fresh sign-in by default)
#   add_passkey(c, auth, ...)    the first passkey (fresh sign-in) or another (proof of one held)
#   proof(c, auth, purpose, t)   a passkey check made in this browser
#   link_code(c, auth)           Integrations -> Phone app -> Link a phone: the 8 characters
#   link(app, code, key, ...)    POST /phone/link as the app sends it
#   door(app, key, device, ...)  a signed door request (tests/r7_fakes.py `sign_request`)
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from book_show_fakes import RecordingNotifier
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from passkey_fakes import SoftAuthenticator
from pydantic import SecretStr
from r7_fakes import phone_key, sign_request

from jarvis.api import create_app
from jarvis.api.identity import user_id_for_email
from jarvis.config import AuthMode, Settings
from jarvis.core.guardrails import ConfirmationGate
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.mobile.ports import PACKAGE
from jarvis.tools import AuditLog, Gateway, Policy, ToolRegistry
from jarvis.tools.builtin import InMemoryWorld, builtin_tools

ORIGIN = "http://test"
OWNER = "phone.owner@example.com"
SECOND = "second.owner@example.com"
CSRF = {"X-Requested-With": "JARVIS"}
BEARER = {"Authorization": "Bearer cli-token"}
FINGERPRINT = "ab" * 32  # a made-up signing fingerprint (32 bytes)
T_START = 1_794_565_800.0  # the shared vectors' server time (13 Nov 2026)


class Tick:
    """Part C's clock (epoch seconds): the tests move it."""

    def __init__(self, t: float = T_START) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def owner_uid(email: str = OWNER) -> str:
    return user_id_for_email(email)


def phone_settings(settings: Settings, **extra: Any) -> Settings:
    return settings.model_copy(
        update={
            "auth_mode": AuthMode.GOOGLE,
            "google_client_id": "cid.apps.googleusercontent.com",
            "google_client_secret": SecretStr("gsecret"),
            "owner_emails": [OWNER, SECOND],
            "session_secret": SecretStr("x" * 32),
            "public_base_url": ORIGIN,
            "api_token": SecretStr("cli-token"),
            **extra,
        }
    )


def _gateway() -> Gateway:
    reg = ToolRegistry()
    for t in builtin_tools(InMemoryWorld()):
        reg.register(t)
    return Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())


@asynccontextmanager
async def phone_app(settings: Settings, *, google: bool = True, **extra: Any) -> AsyncIterator[Any]:
    s = phone_settings(settings, **extra) if google else settings.model_copy(update=extra)
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore(), gateway=_gateway())
    async with app.router.lifespan_context(app):
        app.state.phone_clock = Tick()
        app.state.notify = RecordingNotifier()
        yield app


def phone_service(app: FastAPI) -> Any:
    """Part C's service, as its part handed it to the app."""
    return app.state.r7_parts["phone"].services["phone"]


def http_routes(app: FastAPI) -> list[tuple[str, frozenset[str]]]:
    """(path, methods) of every HTTP route, through FastAPI's included routers."""
    out: list[tuple[str, frozenset[str]]] = []

    def walk(routes: Any) -> None:
        for r in routes:
            if hasattr(r, "effective_candidates"):
                walk(r.effective_candidates())
                continue
            route = getattr(r, "original_route", r)
            methods = getattr(route, "methods", None)
            if methods:
                out.append((str(getattr(r, "path", "")), frozenset(methods)))

    walk(app.routes)
    return out


def audit_entries(app: FastAPI) -> list[Any]:
    return list(app.state.gateway.audit._entries)


@asynccontextmanager
async def browser(
    app: FastAPI, email: str = OWNER, *, fresh: bool = True, from_app: bool = False
) -> AsyncIterator[AsyncClient]:
    """A browser signed in with Google (again, < 5 minutes ago, when `fresh`); `from_app`: the
    installed app's session (the page said it opened at /?source=app)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as c:

        async def fake(request: Any) -> dict[str, Any]:
            return {"userinfo": {"email": email, "email_verified": True, "sub": email}}

        app.state.oauth.google.authorize_access_token = fake
        if fresh:
            await c.get("/auth/login?reauth=1", follow_redirects=False)
        r = await c.get("/auth/callback?code=abc&state=s", follow_redirects=False)
        assert r.status_code == 302, r.text
        if from_app:
            r = await c.post("/v1/session/app", headers=CSRF)
            assert r.status_code == 200, r.text
        yield c


async def proof(
    c: AsyncClient, auth: SoftAuthenticator, purpose: str, target: str | None = None
) -> dict[str, Any]:
    body: dict[str, Any] = {"purpose": purpose}
    if target is not None:
        body["target"] = target
    r = await c.post("/v1/passkeys/challenge", json=body, headers=CSRF)
    assert r.status_code == 200, r.text
    ch = r.json()
    return {"challenge_id": ch["challenge_id"], "credential": auth.get(ch["public_key"])}


async def add_passkey(
    c: AsyncClient,
    auth: SoftAuthenticator | None = None,
    *,
    held: SoftAuthenticator | None = None,
    label: str = "Laptop",
) -> SoftAuthenticator:
    """A passkey made in this browser: the first one (fresh sign-in) or another (`held` proves)."""
    auth = auth or SoftAuthenticator(origin=ORIGIN)
    body = {"proof": await proof(c, held, "add")} if held is not None else {}
    r = await c.post("/v1/passkeys/register/options", json=body, headers=CSRF)
    assert r.status_code == 200, r.text
    opts = r.json()
    r = await c.post(
        "/v1/passkeys/register",
        json={
            "challenge_id": opts["challenge_id"],
            "credential": auth.create(opts["public_key"]),
            "label": label,
        },
        headers=CSRF,
    )
    assert r.status_code == 200, r.text
    return auth


async def link_code(c: AsyncClient, auth: SoftAuthenticator | None = None) -> str:
    """Integrations -> Phone app -> Link a phone, with the passkey (or the fresh sign-in)."""
    r = await c.post("/v1/phone/link-code", json={}, headers=CSRF)
    assert r.status_code == 200, r.text
    if "code" in r.json():
        return str(r.json()["code"])
    assert r.json()["needs"] == "passkey", r.text
    target = r.json()["target"]
    assert auth is not None, "a passkey is in force: pass the authenticator"
    body = {"id": target, "proof": await proof(c, auth, "phone_link", target)}
    r = await c.post("/v1/phone/link-code", json=body, headers=CSRF)
    assert r.status_code == 200, r.text
    return str(r.json()["code"])


def x962(key: ec.EllipticCurvePrivateKey) -> str:
    return (
        key.public_key()
        .public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        .hex()
    )


def link_body(code: str, key: ec.EllipticCurvePrivateKey, **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "v": 1,
        "code": code,
        "public_key": x962(key),
        "package": PACKAGE,
        "fingerprint": FINGERPRINT,
        "model": "phone",
        "app_version": "7.0.0",
    }
    body.update(over)
    return body


async def link(
    app: FastAPI, code: str, key: ec.EllipticCurvePrivateKey | None = None, **over: Any
) -> tuple[Response, ec.EllipticCurvePrivateKey]:
    """POST /phone/link as the app sends it (no cookie, no header)."""
    key = key or phone_key()
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as c:
        r = await c.post("/phone/link", content=json.dumps(link_body(code, key, **over)))
    return r, key


async def linked_phone(app: FastAPI, c: AsyncClient, auth: Any = None) -> tuple[str, Any]:
    """A linked phone: (device id, its key)."""
    r, key = await link(app, await link_code(c, auth))
    assert r.status_code == 200, r.text
    return str(r.json()["device_id"]), key


async def door(
    app: FastAPI,
    key: ec.EllipticCurvePrivateKey,
    device: str,
    route: str,
    payload: Any,
    *,
    t: float | None = None,
    nonce: str | None = None,
    url: str | None = None,
    headers: dict[str, str] | None = None,
    client: AsyncClient | None = None,
) -> Response:
    when = int(app.state.phone_clock() if t is None else t)
    signed, body = sign_request(
        key, device, "POST", f"/phone/v1/{route}", payload, t=when, nonce=nonce
    )
    target = url or f"/phone/v1/{route}"
    if client is not None:
        return await client.post(target, content=body, headers={**signed, **(headers or {})})
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as c:
        return await c.post(target, content=body, headers={**signed, **(headers or {})})


HELLO = {
    "v": 1,
    "app_version": "7.0.0",
    "version_code": 1,
    "model": "phone",
    "android": 36,
    "can": {
        "notifications": True,
        "health_read": True,
        "health_background": False,
        "location": True,
        "folder": False,
        "tile": True,
    },
}


__all__ = [
    "BEARER",
    "CSRF",
    "FINGERPRINT",
    "HELLO",
    "ORIGIN",
    "OWNER",
    "SECOND",
    "T_START",
    "Tick",
    "add_passkey",
    "audit_entries",
    "browser",
    "door",
    "http_routes",
    "link",
    "link_body",
    "link_code",
    "linked_phone",
    "owner_uid",
    "phone_app",
    "phone_service",
    "phone_settings",
    "proof",
    "x962",
]
