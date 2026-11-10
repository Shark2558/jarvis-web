# tests/test_r6_wiring.py -- R6 I1: the build book wired on the app (docs/plans/r6-build-book.md
# "I1", D6, D7, D9, D10, D14, D16). Without the server's keyring every part is None (book OFF,
# `GET /v1/book` says why with a 200); with it A's source, B's vault/sealer/tickets/settings and
# C's sessions/lock/talk/service are on app.state, nothing is sealed at start-up, the two jobs run
# on the tick AND the 5-minute watchdog (advisory there), one Book settings name is shared by B, C
# and D, a close drops the session's download tickets, and an expired session that reaches one of
# B's routes is closed with its audit line and its notice exactly once (B-sec M3).
from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from book_app_fakes import (
    CSRF,
    SECOND_OWNER,
    book,
    book_app,
    open_book,
    owner_uid,
    register_passkey,
    sign_in,
)
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

import jarvis.api.book_gate as book_gate
import jarvis.api.r6_wiring as r6
from jarvis.api import create_app
from jarvis.api.book_lock import ShowLockMiddleware
from jarvis.buildbook.owner import BookSettings, BookSettingsPatch, BookTickets
from jarvis.buildbook.release import ReleaseSource
from jarvis.buildbook.seal import DocsBookVault
from jarvis.buildbook.sealer import BookSealer
from jarvis.buildbook.service import BookService
from jarvis.config import Settings
from jarvis.home.watchdog import ADVISORY_JOBS
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.vault.unlock import TicketGone

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "book" / "_book"
READER = ROOT / "src" / "jarvis" / "api" / "static" / "console-book-reader.js"
KEY_B64 = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="


@pytest.fixture
def keyed(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setattr(r6, "default_source", lambda: ReleaseSource(FIXTURE))
    return settings.model_copy(update={"token_key": SecretStr(KEY_B64)})


@pytest.fixture
async def keyed_app(keyed: Settings) -> AsyncIterator[Any]:
    app = create_app(keyed, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        yield app


async def _book_rows(app: Any) -> list[str]:
    tail = await app.state.gateway.audit.tail(200)
    return [e.tool for e in tail.entries if e.tool.startswith("book_")]


# ---- off and on --------------------------------------------------------------------------------
async def test_without_the_keyring_the_book_is_off_and_status_says_why(settings: Settings) -> None:
    app = create_app(settings, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        assert all(getattr(app.state, name) is None for name in r6.R6_STATE)
        assert r6.r6_tick_jobs(app) == () and r6.r6_privacy_sources(app) == ()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/v1/book")
    # D's panel shows the reason; a 200 so the console logs no error (INTEGRATION-D 4)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["available"] is False and "build book" in body["reason"].lower()
    assert body["sealed"] == [] and body["session"] is None and body["lock"] == {"on": False}


async def test_with_the_keyring_every_part_is_wired_and_nothing_is_sealed_at_start(
    keyed_app: Any,
) -> None:
    st = keyed_app.state
    assert all(getattr(st, name) is not None for name in r6.R6_STATE)
    assert isinstance(st.book_source, ReleaseSource) and isinstance(st.book_vault, DocsBookVault)
    assert isinstance(st.book_sealer, BookSealer) and isinstance(st.book_tickets, BookTickets)
    assert isinstance(st.book_service, BookService)
    assert st.book_service.source is st.book_source  # one source for B and C
    # D7: never at start-up -- no release sealed, no notice, no audit line
    assert await st.book_vault.releases(owner_uid("owner@example.com")) == ()
    assert await _book_rows(keyed_app) == []


async def test_a_book_that_fails_to_build_never_stops_jarvis(
    keyed: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("a bad setting")

    said: list[tuple[str, Any]] = []
    monkeypatch.setattr(r6, "DocsBookVault", broken)
    monkeypatch.setattr(
        r6.log, "error", lambda msg, *_a, **kw: said.append((msg, kw["extra"]["error"]))
    )
    app = create_app(keyed, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):  # JARVIS still starts (as R4's optional parts)
        assert all(getattr(app.state, name) is None for name in r6.R6_STATE)
        assert r6.r6_tick_jobs(app) == ()
    assert said == [("The build book is OFF: its setup failed", "RuntimeError")]


async def test_the_jobs_ride_the_tick_and_the_watchdog_and_never_503_it(keyed_app: Any) -> None:
    st = keyed_app.state
    names = [j.name for j in st.tick_jobs]
    assert {"book_seal", "book_sweep"} <= set(names) and len(names) == len(set(names))
    assert r6.r6_tick_jobs(keyed_app) is st.book_jobs  # built once: the same instances
    assert {"book_seal", "book_sweep"} <= ADVISORY_JOBS  # a seal over the limit fails each run

    class Dog:  # R5.1's 5-minute home watchdog (Home is off in this app)
        def __init__(self) -> None:
            self.jobs: list[Any] = []

        def extend(self, job: Any) -> None:
            self.jobs.append(job)

    st.book_jobs, st.home_watchdog = None, Dog()
    jobs = r6.r6_tick_jobs(keyed_app)
    assert st.home_watchdog.jobs == list(jobs) and [j.name for j in jobs] == [
        "book_seal",
        "book_sweep",
    ]
    assert r6.r6_tick_jobs(keyed_app) is jobs and len(st.home_watchdog.jobs) == 2  # once


async def test_the_book_rows_are_in_the_privacy_panel_and_faces_stays_last(
    keyed_app: Any,
) -> None:
    view = await keyed_app.state.privacy.view(owner_uid("owner@example.com"))
    ids = [c.id for c in view.categories]
    assert {"book_sealed", "book_sessions", "book_settings"} <= set(ids)
    assert ids[-1] == "faces"


# ---- one name for each Book setting (B's store, C's reader, D's switches) ----------------------
def test_one_name_for_each_book_setting() -> None:
    assert set(r6.SETTINGS_KEYS) == set(BookSettings.model_fields)
    assert set(r6.SETTINGS_KEYS) == set(BookSettingsPatch.model_fields)
    js = READER.read_text(encoding="utf-8")
    switches = set(re.findall(r"sw\('([a-z_]+)'", js))
    assert switches and switches <= set(r6.SETTINGS_KEYS), switches
    assert "talk_through" not in js


async def test_c_reads_the_book_settings_b_stores(settings: Settings) -> None:
    async for app in book_app(settings, real_prefs=True):
        uid = owner_uid()
        patch = BookSettingsPatch(creator_name="Kavya Fixturename", talk_on=False)
        await app.state.book_settings.update(uid, patch)
        talk = await app.state.book_service.talk_state(uid)
        assert talk.on is False and "Book settings" in (talk.why or "")
        words = await app.state.book_service.show.words(uid)
        assert words["by"].startswith("Kavya Fixturename")


# ---- closes ------------------------------------------------------------------------------------
async def test_a_close_drops_the_sessions_download_tickets(settings: Settings) -> None:
    async for app in book_app(settings):
        async with sign_in(app) as c:
            auth = await register_passkey(c)
            token = (await open_book(c, auth, "owner"))["token"]
            st, uid = app.state, owner_uid()
            view = await st.book_service.resolve(uid, token, now=datetime.now(UTC))
            ticket = await st.book_tickets.issue(uid, "4a70683", session=view)
            r = await c.post("/v1/book/close", json={"reason": "end"}, headers=book(token))
            assert r.status_code == 200 and r.json()["closed"] is True
            with pytest.raises(TicketGone):
                await st.book_tickets.take(uid, ticket.ticket)


async def test_an_expired_session_on_a_b_route_is_closed_and_told_once(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    async for app in book_app(settings):
        async with sign_in(app) as c:
            auth = await register_passkey(c)
            token = (await open_book(c, auth, "owner"))["token"]
            later = datetime.now(UTC) + timedelta(minutes=11)  # idle (10 min)
            monkeypatch.setattr(book_gate, "now", lambda *_a, at=later: at)
            for _ in range(2):
                r = await c.get("/v1/book/sections", headers=book(token))
                assert r.status_code == 401 and r.json()["error"] == "session_gone"
            sent = [
                m for _, sig, m in app.state.book_notifier.sent if sig.kind == "book_session_closed"
            ]
            assert len(sent) == 1 and "ended by itself" in sent[0]
            assert (await _book_rows(app)).count("book_close") == 1


async def test_a_guest_token_never_opens_bs_owner_routes(settings: Settings) -> None:
    async for app in book_app(settings):
        async with sign_in(app) as c:
            auth = await register_passkey(c)
            token = (await open_book(c, auth, "guest"))["token"]
            lock = await app.state.book_lock.get(owner_uid())
            assert lock is not None and await app.state.book_lock.lift(owner_uid(), lock.id)
            for path in ("/v1/book/sections", "/v1/book/releases/4a70683/sections"):
                r = await c.get(path, headers=book(token))
                assert r.status_code == 403 and r.json()["error"] == "owner_only", path
            r = await c.post("/v1/book/releases/4a70683/ticket", headers=book(token) | CSRF)
            assert r.status_code == 403 and r.json()["error"] == "owner_only"


# ---- the lock ----------------------------------------------------------------------------------
def test_the_show_lock_is_cs_middleware(settings: Settings) -> None:
    from fastapi import FastAPI

    app = FastAPI()
    r6.install_show_lock(app, settings)
    assert [m.cls for m in app.user_middleware] == [ShowLockMiddleware]


async def test_the_show_reads_the_lock_with_its_cookie_alone(settings: Settings) -> None:
    """D's show learns the lock (and, for the owner whose lock it is, its id: his book_resume
    passkey's target) from `GET /v1/book/show/lock`, which passes under the lock (D10)."""
    async for app in book_app(settings):
        async with sign_in(app) as c:
            assert (await c.get("/v1/book/show/lock")).json() == {"on": False}
            auth = await register_passkey(c)
            await open_book(c, auth, "guest")
            r = await c.get("/v1/book/show/lock")
            got = r.json()
            assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
            assert got["on"] is True and re.fullmatch(r"bl_[0-9a-f]{12}", got["id"])
            assert got["line"] == "Please hand the device back to my owner."
            async with sign_in(app, SECOND_OWNER) as other:  # held too, but not his to lift
                assert (await other.get("/v1/book/show/lock")).json() == {
                    "on": True,
                    "line": got["line"],
                }


async def test_a_reply_is_spoken_by_its_id_from_this_session_only(settings: Settings) -> None:
    """D speaks a guarded reply by its id (`r_...`): its text never goes back to the server."""
    async for app in book_app(settings):
        async with sign_in(app) as c:
            auth = await register_passkey(c)
            h = book((await open_book(c, auth, "owner"))["token"])
            svc, uid = app.state.book_service, owner_uid()
            asked = []
            for text in ("How does a conversation turn work?", "What is your owner's e-mail?"):
                r = await c.post("/v1/book/show/ask", json={"text": text}, headers=h)
                asked.append(r.json())
            assert not asked[0]["refused"] and asked[1]["refused"]
            view = await svc.resolve(uid, h["X-Jarvis-Book"], now=datetime.now(UTC))
            for got in asked:
                assert await svc.line_text(uid, view, got["reply_id"]) == got["reply"]
            assert await svc.line_text(uid, view, "r_" + "0" * 12) is None
            h2 = book((await open_book(c, auth, "owner"))["token"])  # a new session
            view2 = await svc.resolve(uid, h2["X-Jarvis-Book"], now=datetime.now(UTC))
            assert await svc.line_text(uid, view2, asked[0]["reply_id"]) is None
