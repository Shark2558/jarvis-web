# tests/test_book_show_api.py -- R6 D8-D14 through the real app: opening takes a passkey AND a
# Google sign-in from the last 5 minutes (console only; no sign-in-only fallback; the proof is
# bound to its audience), the token opens the show routes, a guest open locks every console and
# consumes the fresh sign-in, the close wipes and tells, only a book_resume proof lifts the lock
# (or, when no passkey is in force any more after a completed reset, a fresh sign-in).
from __future__ import annotations

import io
import wave
from collections.abc import AsyncIterator
from typing import Any

import pytest
from book_app_fakes import (
    BEARER,
    CSRF,
    book,
    book_app,
    open_book,
    owner_uid,
    proof,
    register_passkey,
    sign_in,
)
from book_show_fakes import Clock, FixtureSource
from httpx import AsyncClient

from jarvis.api.ratelimit import RateLimiter
from jarvis.buildbook.lines import LINES
from jarvis.config import Settings


def wav(seconds: float) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16_000)
        w.writeframes(b"\x00\x00" * int(16_000 * seconds))
    return out.getvalue()


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[Any]:
    async for a in book_app(settings):
        a.state.book_clock = Clock()
        yield a


async def _audit(app: Any) -> list[tuple[str, str]]:
    tail = await app.state.gateway.audit.tail(100)
    return [(e.tool, e.outcome) for e in tail.entries if e.tool.startswith("book_")]


async def test_opening_needs_the_console_a_passkey_and_a_fresh_sign_in(app: Any) -> None:
    async with AsyncClient(transport=app.transport, base_url="http://test", headers=BEARER) as cli:
        r = await cli.post("/v1/book/open", json={"audience": "owner"})
        assert r.status_code == 403 and r.json()["error"] == "console_only"
    async with sign_in(app) as c:
        r = await c.post("/v1/book/open", json={"audience": "owner"}, headers=CSRF)
        assert r.status_code == 403 and r.json()["error"] == "passkey_setup_needed"
        auth = await register_passkey(c)
        r = await c.post("/v1/book/open", json={"audience": "owner"}, headers=CSRF)
        assert r.status_code == 403 and r.json()["error"] == "passkey_required"
        r = await c.post("/v1/book/open", json={"audience": "x"}, headers=CSRF)
        assert r.status_code == 422 and r.json()["error"] == "input_rejected"
        wrong = await proof(c, auth, "vault_unlock", None)
        r = await c.post("/v1/book/open", json={"audience": "owner", "proof": wrong}, headers=CSRF)
        assert r.status_code == 403 and r.json()["reason"] == "wrong_action"
        owners = await proof(c, auth, "book_open", "owner")
        r = await c.post("/v1/book/open", json={"audience": "guest", "proof": owners}, headers=CSRF)
        assert r.status_code == 403 and r.json()["error"] == "passkey_rejected"  # audience-bound
        r = await c.post("/v1/book/open", json={"audience": "owner"}, headers=CSRF)
        assert r.status_code == 429 and r.headers["retry-after"]  # 5 opens a minute
    app.state.book_show_limits["open"] = RateLimiter(5)
    async with sign_in(app, fresh=False) as stale:
        r = await stale.post("/v1/book/open", json={"audience": "owner"}, headers=CSRF)
        assert r.status_code == 403 and r.json()["error"] == "reauth_required"
        assert r.json()["reason"] == "reauth" and r.headers["cache-control"] == "no-store"
    refused = await _audit(app)
    assert len(refused) == 5 and {o for _, o in refused} == {"refused"}  # the 422 isn't one


async def test_a_guest_show_from_open_to_resume(app: Any) -> None:
    async with sign_in(app) as c:
        auth = await register_passkey(c)
        opened = await open_book(c, auth, "guest")
        token = opened["token"]
        assert opened["audience"] == "guest" and opened["session_id"].startswith("bk_")
        assert (await c.get("/auth/me")).status_code == 423  # the console is the show now
        reset = await c.post("/v1/passkeys/reset", headers=CSRF)
        assert reset.status_code == 403 and reset.json()["reason"] == "reauth"  # consumed
        script = (await c.get("/v1/book/show/script", headers=book(token))).json()
        assert len(script["scenes"]) == 13 and "month_inr" not in script["costs"]
        q = {"text": "What is your owner's e-mail address?"}
        got = (await c.post("/v1/book/show/ask", json=q, headers=book(token))).json()
        assert got["refused"] and got["reply"] == LINES["refuse_data"] and got["left"] == 19
        assert app.state.book_provider.calls == []
        q = {"text": "How does a conversation turn work?"}
        got = (await c.post("/v1/book/show/ask", json=q, headers=book(token))).json()
        assert not got["refused"] and got["follow_up"] == LINES["anything_else"]
        for _ in range(4):  # the show beats; 23 minutes in all
            app.state.book_clock.advance(minutes=5)
            beat = await c.post("/v1/book/show/beat", headers=book(token))
            assert beat.status_code == 200 and set(beat.json()) == {"until", "idle_until"}
        app.state.book_clock.advance(minutes=3)
        r = await c.post("/v1/book/close", json={"reason": "closing"}, headers=book(token))
        assert r.json() == {"closed": True, "wiped": True, "notified": True}
        assert (await c.get("/v1/book/show/script", headers=book(token))).status_code == 401
        locked = await c.get("/auth/me")
        assert locked.status_code == 423  # the hand-back: still locked
        r = await c.post("/v1/book/resume", json={}, headers=CSRF)
        assert r.status_code == 403 and r.json()["error"] == "passkey_required"
        lock_id = r.json()["lock_id"]
        assert lock_id == locked.json()["lock_id"]
        wrong = await proof(c, auth, "book_resume", "bl_000000000000")
        r = await c.post("/v1/book/resume", json={"proof": wrong}, headers=CSRF)
        assert r.status_code == 403 and r.json()["error"] == "passkey_rejected"
        good = await proof(c, auth, "book_resume", lock_id)
        r = await c.post("/v1/book/resume", json={"proof": good}, headers=CSRF)
        assert r.json() == {"resumed": True}
        assert (await c.get("/auth/me")).status_code == 200
        again = await c.post("/v1/book/resume", json={}, headers=CSRF)
        assert again.json()["resumed"] is False
    tools = await _audit(app)
    assert tools == [
        ("book_open", "executed"),
        ("book_close", "executed"),
        ("book_resume", "refused"),  # no proof
        ("book_resume", "refused"),  # a proof for another lock
        ("book_resume", "executed"),
    ]
    [(_, signal, message)] = app.state.book_notifier.sent
    assert signal.kind == "book_session_closed" and "(23 min, 2 questions)" in message


async def test_tokens_end_with_their_session(app: Any) -> None:
    async with sign_in(app) as c:
        auth = await register_passkey(c)
        token = (await open_book(c, auth, "owner"))["token"]
        owner = (await c.get("/v1/book/show/script", headers=book(token))).json()
        assert owner["costs"]["month_inr"] == 0.0 and owner["closing"]["hand_back"] is None
        assert (await c.get("/auth/me")).status_code == 200  # an owner session locks nothing
        for bad in ("", "x" * 43, token[:-1] + ("A" if token[-1] != "A" else "B")):
            r = await c.get("/v1/book/show/script", headers=book(bad))
            assert r.status_code == 401 and r.json()["error"] == "session_gone"
        app.state.book_clock.advance(minutes=11)  # idle
        assert (await c.post("/v1/book/show/beat", headers=book(token))).status_code == 401
        assert "ended by itself" in app.state.book_notifier.sent[0][2]
        token2 = (await open_book(c, auth, "owner"))["token"]
        token3 = (await open_book(c, auth, "owner"))["token"]  # a new open ends the old one
        assert (await c.post("/v1/book/show/beat", headers=book(token2))).status_code == 401
        assert (await c.post("/v1/book/show/beat", headers=book(token3))).status_code == 200


async def test_speaking_and_hearing(app: Any) -> None:
    async with sign_in(app) as c:
        auth = await register_passkey(c)
        h = book((await open_book(c, auth, "owner"))["token"])
        r = await c.post("/v1/book/show/speak", json={"line_id": "s02b02"}, headers=h)
        assert r.status_code == 503 and r.json()["error"] == "voice_unavailable"
        sid = (await c.get("/v1/book/show/script", headers=h)).json()["session"]
        assert app.state.book_service.allow_speech("bk_0000000000000000", 1)
        r = await c.post("/v1/book/show/speak", json={"line_id": "s99b99"}, headers=h)
        assert r.status_code == 404 and r.json()["error"] == "unknown_line"
        assert sid["questions_left"] == 20
        live = await app.state.book_sessions.live(owner_uid(), now=app.state.book_clock())
        while app.state.book_service.allow_speech(live.session_id, 1):
            pass  # the session's budget, used up
        r = await c.post("/v1/book/show/speak", json={"line_id": "ask"}, headers=h)
        assert r.status_code == 503 and r.json()["reason"] == "budget"
        app.state.book_prefs.values["show_voice"] = "browser"
        r = await c.post("/v1/book/show/speak", json={"line_id": "ask"}, headers=h)
        assert r.status_code == 503 and r.json()["reason"] == "browser"
        r = await c.post("/v1/book/show/hear", content=b"{}", headers=h)
        assert r.status_code == 422
        wav_h = {**h, "Content-Type": "audio/wav"}
        r = await c.post("/v1/book/show/hear", content=wav(16), headers=wav_h)
        assert r.status_code == 413 and r.json()["error"] == "too_long"
        r = await c.post("/v1/book/show/hear", content=wav(1) + b"\x00" * 700_000, headers=wav_h)
        assert r.status_code == 413
        r = await c.post("/v1/book/show/hear", content=wav(1), headers=wav_h)
        assert r.status_code == 503 and r.json()["error"] == "voice_unavailable"


async def test_question_limits(app: Any) -> None:
    async with sign_in(app) as c:
        auth = await register_passkey(c)
        h = book((await open_book(c, auth, "guest"))["token"])
        r = await c.post("/v1/book/show/ask", json={"text": "x" * 501}, headers=h)
        assert r.status_code == 422 and r.json()["error"] == "too_long"
        r = await c.post("/v1/book/show/ask", json={"text": "   "}, headers=h)
        assert r.status_code == 422
        codes = [
            (
                await c.post("/v1/book/show/ask", json={"text": "How does voice work?"}, headers=h)
            ).status_code
            for _ in range(5)
        ]
        assert codes == [200, 200, 200, 200, 429]  # 6 a minute, the two 422s counted


async def test_resume_without_any_passkey_left_needs_a_fresh_sign_in(app: Any) -> None:
    async with sign_in(app) as c:
        auth = await register_passkey(c)
        await open_book(c, auth, "guest")

    async def none_in_force(*a: Any, **k: Any) -> None:
        return None  # the 24-hour reset has removed every passkey

    app.state.permissions.check_purpose = none_in_force
    async with sign_in(app, fresh=False) as stale:
        r = await stale.post("/v1/book/resume", json={}, headers=CSRF)
        assert r.status_code == 403 and r.json()["error"] == "reauth_required"
    async with sign_in(app) as fresh:
        r = await fresh.post("/v1/book/resume", json={}, headers=CSRF)
        assert r.json() == {"resumed": True}
        assert (await fresh.get("/auth/me")).status_code == 200


async def test_no_book_on_this_server(settings: Settings) -> None:
    async for app in book_app(settings, source=FixtureSource(present=False)):
        async with sign_in(app) as c:
            r = await c.post("/v1/book/open", json={"audience": "owner"}, headers=CSRF)
            assert r.status_code == 404 and r.json()["error"] == "no_book"


async def test_token_mode_dev_opens_for_the_owner_only(settings: Settings) -> None:
    async for app in book_app(settings, google=False):
        async with AsyncClient(transport=app.transport, base_url="http://test") as c:
            r = await c.post("/v1/book/open", json={"audience": "guest"})
            assert r.status_code == 409 and r.json()["error"] == "guest_needs_google"
            r = await c.post("/v1/book/open", json={"audience": "owner"})
            assert r.status_code == 200 and r.json()["audience"] == "owner"
            r = await c.post("/v1/book/resume", json={})
            assert r.status_code == 403 and r.json()["error"] == "console_only"


def test_owner_ids_differ_per_owner() -> None:
    assert owner_uid() != owner_uid("second.owner@example.com")
