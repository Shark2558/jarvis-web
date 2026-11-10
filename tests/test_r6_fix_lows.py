# tests/test_r6_fix_lows.py -- R6 integrated code review LOWs.
# L2: `GET /v1/book` gives the true reason the book is off (no key vs setup failed), and a setup
#     failure shows on the Vitals board (the error class only, never a message or a secret).
# L3: BookTickets, BookSweepJob and the privacy wipe read `app.state.book_clock`, as B's and C's
#     routes do (a moved clock never makes a live session look over, or an old one look live).
# L4: the 5-minute watchdog answers inside its 60 s Scheduler deadline: its run is capped below it
#     and an advisory book job cut short is "degraded", never a failed run.
from __future__ import annotations

import asyncio
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from book_app_fakes import CSRF, book, book_app, open_book, owner_uid, register_passkey, sign_in
from book_show_fakes import Clock, FixtureSource
from pydantic import SecretStr

import jarvis.api.r6_wiring as r6
from jarvis.api import create_app
from jarvis.api.book_status import NO_KEY, SETUP_FAILED
from jarvis.config import Settings
from jarvis.home import watchdog as wd
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore

ROOT = Path(__file__).resolve().parents[1]
KEY_B64 = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="


class Secretive(RuntimeError):
    pass


# ---- L2: the true reason, and Vitals ------------------------------------------------------------
async def _status(app: Any) -> dict[str, Any]:
    async with sign_in(app) as c:
        r = await c.get("/v1/book")
        assert r.status_code == 200
        return dict(r.json())


async def test_the_panel_says_why_the_book_is_off(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    async for app in book_app(settings):
        s = app.state.settings
        await r6.wire_r6(app, s, app.state.book_docs, app.state.gateway.audit)
        assert (await _status(app))["reason"] == NO_KEY

        def broken(*_a: Any, **_k: Any) -> Any:
            raise Secretive("token sk-ant-SECRET at /srv/key")

        monkeypatch.setattr(r6, "DocsBookVault", broken)
        monkeypatch.setattr(r6, "default_source", lambda: FixtureSource())
        keyed = s.model_copy(update={"token_key": SecretStr(KEY_B64)})
        await r6.wire_r6(app, keyed, app.state.book_docs, app.state.gateway.audit)
        body = await _status(app)
        assert body["available"] is False and body["reason"] == SETUP_FAILED
        assert "SECRET" not in str(body) and app.state.book_off_error == "Secretive"


async def test_a_setup_failure_shows_on_vitals_with_its_error_class_only(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_a: Any, **_k: Any) -> Any:
        raise Secretive("token sk-ant-SECRET at /srv/key")

    keyed = settings.model_copy(update={"token_key": SecretStr(KEY_B64), "vitals_enabled": True})
    monkeypatch.setattr(r6, "DocsBookVault", broken)
    monkeypatch.setattr(r6, "default_source", lambda: FixtureSource())
    app = create_app(keyed, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        board = (await app.state.vitals.board(owner_uid())).to_json()
    items = {i["id"]: i for i in board["items"]}
    item = items["build_book"]
    assert item["status"] == "amber" and "Secretive" in item["note"]
    assert "SECRET" not in str(item).replace("Secretive", "")


async def test_a_book_that_started_is_not_on_vitals(settings: Settings) -> None:
    keyed = settings.model_copy(update={"token_key": SecretStr(KEY_B64), "vitals_enabled": True})
    app = create_app(keyed, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        board = (await app.state.vitals.board(owner_uid())).to_json()
    assert "build_book" not in {i["id"] for i in board["items"]}


# ---- L3: one clock ------------------------------------------------------------------------------
async def test_tickets_the_sweep_and_the_wipe_read_the_book_clock(settings: Settings) -> None:
    async for app in book_app(settings):
        clock = Clock(datetime.now(UTC) - timedelta(days=1))
        app.state.book_clock = clock
        async with sign_in(app) as c:
            auth = await register_passkey(c)
            h = book((await open_book(c, auth, "owner"))["token"])
            rid = (await c.get("/v1/book")).json()["release"]["id"]
            r = await c.post(f"/v1/book/releases/{rid}/ticket", headers=h | CSRF)
            assert r.status_code in (200, 404), r.text  # never 401 session_gone for a live one
            assert r.status_code != 401
            # the sweep on the moved clock: nothing is over yet ...
            (sweep,) = [j for j in r6.r6_tick_jobs(app) if j.name == "book_sweep"]
            assert (await sweep.run([owner_uid()])).get("closed", 0) == 0
            assert (await c.get("/v1/book")).json()["session"] is not None
            # ... and 46 minutes later on it, the session is over
            clock.advance(minutes=46)
            await sweep.run([owner_uid()])
            assert (await c.get("/v1/book")).json()["session"] is None
        # the Privacy wipe reads the same clock
        (rows,) = [s for s in r6.r6_privacy_sources(app) if s.id == "book_sessions"]
        assert rows._clock() == clock()  # noqa: SLF001 - the source's clock is the book's


# ---- L4: the watchdog inside its deadline -------------------------------------------------------
def test_the_watchdog_budget_is_below_the_schedulers_deadline() -> None:
    script = (ROOT / "deploy" / "cloudrun.sh").read_text("utf-8")
    block = script[script.index('--schedule "*/5 * * * *"') :]
    deadline = int(re.search(r"--attempt-deadline (\d+)s", block).group(1))  # type: ignore[union-attr]
    assert wd.WATCHDOG_BUDGET_S + 5 <= deadline


class Slow:
    budget_s = 45.0

    def __init__(self, name: str) -> None:
        self.name = name

    async def run(self, owners: Any) -> dict[str, int]:
        await asyncio.sleep(10)
        return {}


async def test_a_slow_advisory_book_job_is_cut_inside_the_watchdogs_budget() -> None:
    from jarvis.home.store import HomeStore
    from jarvis.keyring import Keyring
    from jarvis.storage.docs import MemoryDocs

    store = HomeStore(MemoryDocs(), Keyring(bytes(range(1, 33))), clock=time.time)
    offline = wd.OfflineJob(store, None, None, clock=time.time, offline_after_s=360)
    dog = wd.Watchdog(store, offline, budget_s=0.3)
    dog.extend(Slow("book_seal"))
    started = time.monotonic()
    out = await dog.run()
    assert time.monotonic() - started < 1.5
    assert out["jobs"]["book_seal"] == "degraded"  # type: ignore[index]
