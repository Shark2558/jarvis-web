# tests/test_r62_book_open.py -- R6.2 Part 1, gap G11 (Phase A findings, decision 6): the build book
# never opens without the passkey AND a fresh Google sign-in, including for local development
# (owner rule 1). Token mode, dev or not, refuses every open (403 google_needed), audited as a
# refusal; no session is made. The local way to try the Book stays Google mode (with its passkey),
# as tests/book_app_fakes does with a fake Google sign-in.
from __future__ import annotations

from typing import Any

import pytest
from book_app_fakes import CSRF, book_app, open_book, owner_uid, register_passkey, sign_in
from book_show_fakes import Clock
from httpx import AsyncClient
from pydantic import SecretStr

from jarvis.api.book_show_access import GOOGLE_NEEDED
from jarvis.config import Settings

TOKEN = "r62-token-not-a-secret"


async def _book_audit(app: Any) -> list[tuple[str, str]]:
    tail = await app.state.gateway.audit.tail(100)
    return [(e.tool, e.outcome) for e in tail.entries if e.tool.startswith("book_")]


@pytest.mark.parametrize("env", ["dev", "prod"])
@pytest.mark.parametrize("audience", ["owner", "guest"])
async def test_token_mode_never_opens_the_book(settings: Settings, env: str, audience: str) -> None:
    s = settings.model_copy(update={"env": env, "api_token": SecretStr(TOKEN)})
    bearer = {"Authorization": f"Bearer {TOKEN}"}
    async for app in book_app(s, google=False):
        app.state.book_clock = Clock()
        async with AsyncClient(
            transport=app.transport, base_url="http://test", headers=bearer
        ) as c:
            r = await c.post("/v1/book/open", json={"audience": audience})
            assert r.status_code == 403
            assert r.json() == {"error": "google_needed", "detail": GOOGLE_NEEDED}
            assert r.headers["cache-control"] == "no-store"
        assert await _book_audit(app) == [("book_open", "refused")]
        assert await app.state.book_sessions.live(owner_uid(), now=app.state.book_clock()) is None


async def test_google_mode_still_opens_with_the_passkey_and_a_fresh_sign_in(
    settings: Settings,
) -> None:
    """The local way to try the Book: Google mode with a passkey (the tests' fake sign-in)."""
    async for app in book_app(settings):
        app.state.book_clock = Clock()
        async with sign_in(app) as c:
            r = await c.post("/v1/book/open", json={"audience": "owner"}, headers=CSRF)
            assert r.status_code == 403 and r.json()["error"] == "passkey_setup_needed"
            auth = await register_passkey(c)
            r = await c.post("/v1/book/open", json={"audience": "owner"}, headers=CSRF)
            assert r.status_code == 403 and r.json()["error"] == "passkey_required"
            opened = await open_book(c, auth, "owner")
            assert opened["audience"] == "owner" and opened["token"]
        tools = await _book_audit(app)
        assert ("book_open", "executed") in tools


def test_the_refusal_names_what_the_book_needs_and_no_secret() -> None:
    assert "Google sign-in" in GOOGLE_NEEDED and "passkey" in GOOGLE_NEEDED
    assert "JARVIS_AUTH_MODE=google" in GOOGLE_NEEDED  # the owner's console only, never a guest
