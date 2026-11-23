# tests/test_r63_wiring.py -- R6.3 I0 seams 6 and 7 (docs/plans/r6-3-book-content.md D5, D8, D13,
# M3, L11): part B's writer on the app through its ONE join (`buildbook/writer/part.build(ctx)`).
# With the keyring the writer's service is on app.state; without it, nothing. `book_write` rides the
# morning tick after `book_sweep` and the ONE 5-minute clock LAST (Home on or off), never the home
# watchdog's R6 loop; it is advisory; a broken part leaves the rest of the Book on; every new route
# answers 503 `not_built_yet` (console routes refuse a script first); the Privacy row is there;
# Vitals labels the writer's spend "Book writer".
from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from book_app_fakes import CSRF, book_app, owner_uid, sign_in
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from r63_fake_brains import claude_like, gemini_like, provider_of, registry

import jarvis.api.r6_wiring as r6
import jarvis.api.tick_wiring as tick_wiring
from jarvis.api import book_writer_wiring as writer_wiring
from jarvis.api import create_app
from jarvis.api.identity import primary_user_id
from jarvis.api.scheduler_auth import WATCHDOG_PATH, require_scheduler
from jarvis.billing.service import LABELS
from jarvis.buildbook.release import ReleaseSource
from jarvis.buildbook.writer import part as writer_part
from jarvis.buildbook.writer.http import NOT_BUILT, ROUTES
from jarvis.buildbook.writer.job import BookWriteJob
from jarvis.buildbook.writer.ports import WriterContext, WriterPart
from jarvis.config import Settings
from jarvis.home.watchdog import ADVISORY_JOBS
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "book" / "_book"
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


# ---- seam 6 · on and off ------------------------------------------------------------------------
async def test_with_the_keyring_the_writer_is_built_by_its_one_join(keyed_app: Any) -> None:
    st = keyed_app.state
    assert isinstance(st.book_writer, writer_part.WriterService)  # part B's service (I1)
    assert st.book_writer_off is None
    assert isinstance(st.book_writer_part.job, BookWriteJob) and "book_writer" in r6.R6_STATE
    assert r6.R6_JOB_NAMES == frozenset({"book_seal", "book_sweep", "book_write"})


async def test_without_the_keyring_there_is_no_writer(settings: Settings) -> None:
    app = create_app(settings, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        assert app.state.book_writer is None and app.state.book_writer_part is None
        assert "book_write" not in [j.name for j in app.state.clock_jobs]


async def test_a_broken_writer_leaves_the_rest_of_the_book_on(
    keyed: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(ctx: WriterContext) -> WriterPart:
        raise RuntimeError("part B is broken")

    monkeypatch.setattr(writer_part, "build", broken)
    app = create_app(keyed, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        st = app.state
        assert st.book_writer is None and st.book_writer_off == "setup_failed"
        assert st.book_vault is not None and st.book_service is not None and st.book_off is None
        assert [j.name for j in r6.r6_tick_jobs(app)] == ["book_seal", "book_sweep"]


async def test_a_writer_whose_job_is_not_book_write_is_left_out(
    keyed: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Stray(BookWriteJob):
        name = "book_seal"

    monkeypatch.setattr(
        writer_part, "build", lambda ctx: WriterPart(service=object(), job=Stray(ctx))
    )
    app = create_app(keyed, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        assert app.state.book_writer is None and app.state.book_writer_off == "setup_failed"


async def test_the_context_is_the_primary_owners_with_the_apps_brains_and_billing(
    keyed_app: Any,
) -> None:
    st = keyed_app.state
    ctx = st.book_writer_part.job._ctx
    assert ctx.brains is st.brains and ctx.billing is st.billing and ctx.vault is st.book_vault
    assert ctx.source is st.book_source and ctx.uid == primary_user_id(st.settings)  # L11
    assert ctx.prefix == st.settings.firestore_prefix and ctx.limit_mb == 60
    assert ctx.clock().tzinfo is not None
    assert writer_wiring.writer_context is not None


# ---- seam 6 · the clocks (D5, M3) ---------------------------------------------------------------
async def test_book_write_rides_the_tick_after_the_sweep_and_the_clock_last(
    keyed_app: Any,
) -> None:
    st = keyed_app.state
    names = [j.name for j in st.tick_jobs]
    assert names[names.index("book_seal") : names.index("book_seal") + 3] == [
        "book_seal",
        "book_sweep",
        "book_write",
    ]
    clock = [j.name for j in st.clock_jobs]
    assert clock[-1] == "book_write" and clock.count("book_write") == 1
    assert (
        clock.index("outfit_clock") < clock.index("book_write") if "outfit_clock" in clock else True
    )
    assert "book_write" in ADVISORY_JOBS and tick_wiring.LAST_CLOCK_JOBS == ("book_write",)


async def test_the_watchdog_gets_the_seal_and_the_sweep_but_never_the_writer(
    keyed_app: Any,
) -> None:
    class Dog:
        def __init__(self) -> None:
            self.jobs: list[Any] = []

        def extend(self, job: Any) -> None:
            self.jobs.append(job)

    st = keyed_app.state
    st.book_jobs, st.home_watchdog = None, Dog()
    jobs = r6.r6_tick_jobs(keyed_app)
    assert [j.name for j in jobs] == ["book_seal", "book_sweep", "book_write"]
    assert [j.name for j in st.home_watchdog.jobs] == ["book_seal", "book_sweep"]


async def test_with_home_off_the_five_minute_route_runs_book_write(keyed_app: Any) -> None:
    keyed_app.dependency_overrides[require_scheduler] = lambda: None  # the Scheduler's call
    transport = ASGITransport(app=keyed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        out = await c.post(WATCHDOG_PATH)
    keyed_app.dependency_overrides.clear()
    assert out.status_code == 200 and out.json()["jobs"]["book_write"] == "ok"


async def test_the_stub_job_does_nothing_and_calls_no_brain(keyed_app: Any) -> None:
    claude, gemini = claude_like(), gemini_like()
    st = keyed_app.state
    ctx = st.book_writer_part.job._ctx
    job = BookWriteJob(WriterContext(**{**ctx.__dict__, "brains": registry(claude, gemini)}))
    owners: Sequence[str] = (ctx.uid,)
    for _ in range(50):
        assert await job.run(owners) == {}
    assert provider_of(claude).calls == [] and provider_of(gemini).calls == []


# ---- seam 6 · the stub routes, the Privacy row; seam 7 · the label ------------------------------
async def test_every_new_route_answers_from_its_part_and_console_routes_refuse_a_script(
    settings: Settings,
) -> None:
    """I1: B's routes replaced I0's stubs, so no row says not_built_yet; each answers one of the
    statuses its row of the contract lists, never cached."""
    async for app in book_app(settings):
        async with sign_in(app) as c:
            for method, path, _part, _req, _reply, codes, _gate in ROUTES:
                url = path.replace("{nn}", "01").replace("{page_id}", "pg_card_c16")
                r = await c.request(method, url, headers=CSRF, json={} if method != "GET" else None)
                assert r.status_code in (200, *codes), (method, path, r.status_code)
                assert r.json().get("error") != NOT_BUILT, (method, path)
                assert r.headers["cache-control"] == "no-store"
        async with AsyncClient(transport=app.transport, base_url="http://test") as bare:
            r = await bare.get("/v1/book/writer")
            assert r.status_code == 401  # signed in first, always


async def test_the_writer_row_is_in_the_privacy_panel_before_faces(keyed_app: Any) -> None:
    view = await keyed_app.state.privacy.view(owner_uid("owner@example.com"))
    ids = [c.id for c in view.categories]
    assert "book_writer" in ids and ids.index("book_settings") < ids.index("book_writer")
    row = next(c for c in view.categories if c.id == "book_writer")
    assert row.label == "Build book: writer" and row.count == 0


def test_vitals_labels_the_writers_spend_book_writer() -> None:
    assert LABELS["book"] == "Book writer" and LABELS["tryon"] == "Try-on"


async def test_a_script_with_the_token_gets_console_only_on_the_writers_routes(
    keyed_app: Any,
) -> None:
    transport = ASGITransport(app=keyed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        token = keyed_app.state.settings.api_token
        auth = {"Authorization": f"Bearer {token.get_secret_value()}"} if token else {}
        r = await c.get("/v1/book/writer", headers=auth)
    assert r.status_code in (401, 403)  # never served to a script
    if r.status_code == 403:
        assert r.json()["error"] == "console_only"
