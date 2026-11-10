# tests/book_app_fakes.py -- the real app with builder C's parts wired the way I1 will wire them
# (docs/plans/r6-build-book.md "I1"): Google sign-in through the real /auth routes (Google's half
# faked), the show lock installed where `install_show_lock` sits (inside the session middleware),
# C's sessions, lock, talk and service on app.state over their own in-process documents, and a
# software passkey. Imported bare by tests and evals/r6_book.
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import patch

from book_show_fakes import (
    OWNER_EMAIL,
    FixtureSource,
    FlakyDocs,
    Prefs,
    RecordingNotifier,
    WorstCaseProvider,
    keyring,
)
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from passkey_fakes import SoftAuthenticator
from pydantic import SecretStr

import jarvis.api.app as app_module
from jarvis.api import create_app
from jarvis.api.book_lock import install_show_lock_middleware
from jarvis.api.book_show_wiring import wire_book_c
from jarvis.api.identity import user_id_for_email
from jarvis.config import AuthMode, Settings
from jarvis.core.guardrails import ConfirmationGate
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.tools import AuditLog, Gateway, Policy, ToolRegistry
from jarvis.tools.builtin import InMemoryWorld, builtin_tools

ORIGIN = "http://test"
OWNER = OWNER_EMAIL
SECOND_OWNER = "second.owner@example.com"
CSRF = {"X-Requested-With": "JARVIS"}
BEARER = {"Authorization": "Bearer cli-token"}
BOOK = "X-Jarvis-Book"


def owner_uid(email: str = OWNER) -> str:
    return user_id_for_email(email)


def google_settings(settings: Settings, **extra: Any) -> Settings:
    return settings.model_copy(
        update={
            "auth_mode": AuthMode.GOOGLE,
            "google_client_id": "cid.apps.googleusercontent.com",
            "google_client_secret": SecretStr("gsecret"),
            "owner_emails": [OWNER, SECOND_OWNER],
            "session_secret": SecretStr("x" * 32),
            "public_base_url": ORIGIN,
            "api_token": SecretStr("cli-token"),
            **extra,
        }
    )


def gateway() -> Gateway:
    reg = ToolRegistry()
    for t in builtin_tools(InMemoryWorld()):
        reg.register(t)
    return Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())


async def book_app(
    settings: Settings,
    *,
    provider: Any = None,
    source: Any = None,
    prefs: Prefs | None = None,
    notifier: RecordingNotifier | None = None,
    google: bool = True,
) -> AsyncIterator[Any]:
    """The app, signed-in owners possible, C's parts on app.state (plus `book_docs`,
    `book_notifier`, `book_provider`, `transport` for the tests)."""
    s = google_settings(settings) if google else settings
    model = provider or WorstCaseProvider()
    with patch.object(app_module, "install_show_lock", install_show_lock_middleware):
        app = create_app(s, provider=model, store=InMemorySessionStore(), gateway=gateway())
    async with app.router.lifespan_context(app):
        docs, sent, settings_doc = FlakyDocs(), notifier or RecordingNotifier(), prefs or Prefs()
        wire_book_c(
            app,
            s,
            docs,
            app.state.gateway.audit,
            source=source or FixtureSource(),
            keyring=keyring(),
            prefs=settings_doc,
            notifier=sent,
        )
        app.state.book_docs, app.state.book_notifier, app.state.book_provider = docs, sent, model
        app.state.book_prefs = settings_doc
        app.state.transport = ASGITransport(app=app)
        app.transport = app.state.transport  # type: ignore[attr-defined]
        yield app


@asynccontextmanager
async def sign_in(
    app: FastAPI, email: str = OWNER, *, fresh: bool = True
) -> AsyncIterator[AsyncClient]:
    """A browser signed in with Google (again, < 5 minutes ago, when `fresh`)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as c:

        async def fake(request: Any) -> dict[str, Any]:
            return {"userinfo": {"email": email, "email_verified": True, "sub": email}}

        app.state.oauth.google.authorize_access_token = fake
        if fresh:
            await c.get("/auth/login?reauth=1", follow_redirects=False)
        r = await c.get("/auth/callback?code=abc&state=s", follow_redirects=False)
        assert r.status_code == 302, r.text
        yield c


async def register_passkey(c: AsyncClient) -> SoftAuthenticator:
    """The first passkey (the browser signed in again < 5 min ago): the requirement is on."""
    auth = SoftAuthenticator(origin=ORIGIN)
    r = await c.post("/v1/passkeys/register/options", json={}, headers=CSRF)
    assert r.status_code == 200, r.text
    opts = r.json()
    r = await c.post(
        "/v1/passkeys/register",
        json={
            "challenge_id": opts["challenge_id"],
            "credential": auth.create(opts["public_key"]),
            "label": "Laptop",
        },
        headers=CSRF,
    )
    assert r.status_code == 200 and r.json()["require_passkey"] is True, r.text
    return auth


async def proof(
    c: AsyncClient, auth: SoftAuthenticator, purpose: str, target: str | None
) -> dict[str, Any]:
    body: dict[str, Any] = {"purpose": purpose}
    if target is not None:
        body["target"] = target
    r = await c.post("/v1/passkeys/challenge", json=body, headers=CSRF)
    assert r.status_code == 200, r.text
    ch = r.json()
    return {"challenge_id": ch["challenge_id"], "credential": auth.get(ch["public_key"])}


async def open_book(
    c: AsyncClient, auth: SoftAuthenticator, audience: str = "guest"
) -> dict[str, Any]:
    body = {"audience": audience, "proof": await proof(c, auth, "book_open", audience)}
    r = await c.post("/v1/book/open", json=body, headers=CSRF)
    assert r.status_code == 200, r.text
    return dict(r.json())


def book(token: str) -> dict[str, str]:
    return {**CSRF, BOOK: token}


__all__ = [
    "BEARER",
    "BOOK",
    "CSRF",
    "ORIGIN",
    "OWNER",
    "SECOND_OWNER",
    "book",
    "book_app",
    "google_settings",
    "open_book",
    "owner_uid",
    "proof",
    "register_passkey",
    "sign_in",
]
