# tests/test_r6_fix_lock_off.py -- R6 integrated review SEC-3 = CODE-M1: the guest lock holds when
# the build book is off. The lock is a stored document that outlives a revision, and it needs no
# keyring, so in Google mode `app.state.book_lock` is ALWAYS a `DocShowLock(docs, prefix)`: with
# no JARVIS_TOKEN_KEY, and when R6's setup fails. Resume then answers 503 and points to the
# emergency unlock; the middleware fails closed (503) when it has no lock store to read.
from __future__ import annotations

from typing import Any

import pytest
from book_app_fakes import CSRF, book_app, open_book, register_passkey, sign_in
from book_show_fakes import FixtureSource
from pydantic import SecretStr

import jarvis.api.r6_wiring as r6
from jarvis.buildbook.lock import DocShowLock
from jarvis.config import Settings

KEY_B64 = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="


def _broken(*_a: Any, **_k: Any) -> Any:
    raise RuntimeError("a later change broke a constructor")


@pytest.mark.parametrize("why", ["setup_failed", "no_key"])
async def test_a_stored_lock_holds_when_the_book_is_off(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, why: str
) -> None:
    async for app in book_app(settings):
        async with sign_in(app) as c:
            auth = await register_passkey(c)
            await open_book(c, auth, "guest")
            assert (await c.get("/auth/me")).status_code == 423
            # a new revision deploys on the same documents, and its R6 setup fails / has no key
            s = app.state.settings
            if why == "setup_failed":
                s = s.model_copy(update={"token_key": SecretStr(KEY_B64)})
                monkeypatch.setattr(r6, "DocsBookVault", _broken)
            monkeypatch.setattr(r6, "default_source", lambda: FixtureSource())
            await r6.wire_r6(app, s, app.state.book_docs, app.state.gateway.audit)
            st = app.state
            assert st.book_service is None and isinstance(st.book_lock, DocShowLock)
            assert st.book_off == why
            assert (await c.get("/auth/me")).status_code == 423  # not 200: the lock holds
            assert (await c.get("/v1/chat/sessions")).status_code == 423
            r = await c.get("/v1/book/show/lock")
            assert r.status_code == 200 and r.json()["on"] is True
            r = await c.post("/v1/book/resume", json={"proof": {}}, headers=CSRF)
            assert r.status_code == 503 and r.json()["error"] == "book_off"
            assert "python -m jarvis.buildbook.unlock" in r.json()["detail"]


async def test_the_lock_store_is_built_without_a_keyring_in_google_mode(
    settings: Settings,
) -> None:
    async for app in book_app(settings):
        s = app.state.settings
        await r6.wire_r6(app, s, app.state.book_docs, app.state.gateway.audit)
        assert app.state.book_off == "no_key"
        assert isinstance(app.state.book_lock, DocShowLock)
        assert all(getattr(app.state, n) is None for n in r6.R6_STATE if n != "book_lock")


async def test_a_google_app_with_no_lock_store_fails_closed(settings: Settings) -> None:
    async for app in book_app(settings):
        async with sign_in(app) as c:
            app.state.book_lock = None
            r = await c.get("/auth/me")
            assert r.status_code == 503 and r.json()["error"] == "show_lock_unreadable"
            assert (await c.get("/health")).status_code == 200  # the allow-list still passes
