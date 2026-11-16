# tests/test_r13_wiring.py -- R13 I0 (docs/plans/r13-wardrobe.md seam 10): the parts' one join,
# `api/r13_wiring.py`. A part that breaks its contract is left out ("setup failed") and the others
# still run; the services each part may offer reach their one place (A's store, joined with B's
# review writer and every observer, C's refresh first; A's bin for `wardrobe_item`; D's No-AI
# routers, FIRST); the restore's body cap; `GET /v1/r13`; the wardrobe's one clock.
from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from r13_fakes import FixedClock, RecordingObserver, RecordingWriter, ist, memory_store
from r14_fakes import RecordingJob

import jarvis.api.r13_wiring as wiring
from jarvis.config import Settings
from jarvis.core.guardrails import ActionRisk
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.offline.mode import BrainMode
from jarvis.offline.rules import NoAIRoute
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.base import Tool
from jarvis.wardrobe.ports import PARTS, WardrobeContext, WardrobePart


def _tool(name: str) -> Tool:
    async def run(_: dict[str, object]) -> str:
        return "ok"

    return Tool(
        name, "a test tool", {"type": "object", "properties": {}}, ActionRisk.READ_ONLY, run
    )


def _ctx(s: Settings) -> WardrobeContext:
    async def zone(uid: str) -> Any:
        return None

    return WardrobeContext(
        s=s, docs=None, keyring=None, audit=None, now=FixedClock(ist(2026, 11, 16)), zone=zone,
        state={}.get,
    )  # fmt: skip


class _Data:
    name = "laundry"

    async def count(self, uid: str) -> int:
        return 0

    async def export(self, uid: str) -> dict[str, Any]:
        return {}

    async def delete(self, uid: str) -> int:
        return 0


# ---- the contract check -------------------------------------------------------------------------
def test_a_part_that_breaks_its_contract_is_left_out_and_the_rest_stay(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def build(name: str, ctx: WardrobeContext) -> WardrobePart:
        if name == "catalog":
            return WardrobePart("catalog", tools=(_tool("laundry_move"),))  # B's tool
        if name == "laundry":
            raise RuntimeError("boom")
        if name == "styling":
            return WardrobePart("styling", services={"store": object()})  # A's service
        return WardrobePart("phone", tools=(_tool("wardrobe_find"),))  # D has no tool

    monkeypatch.setattr(wiring, "_build", build)
    parts = wiring.build_parts(_ctx(settings))
    assert [p.ready for p in parts.values()] == [wiring.SETUP_FAILED] * 4
    assert wiring.r13_tools(parts) == () and wiring.r13_tools(None) == ()


@pytest.mark.parametrize(
    "part",
    [
        WardrobePart("catalog", tools=(_tool("wardrobe_shout"),)),  # not one of the 18
        WardrobePart("styling", clock_jobs=(RecordingJob("helpers_clock"),)),  # not R13's
        WardrobePart("catalog", clock_jobs=(RecordingJob("wardrobe_sweep"),)),  # daily
        WardrobePart("styling", daily_jobs=(RecordingJob("outfit_clock"),)),  # 5-minute only
        WardrobePart("laundry", daily_jobs=(RecordingJob("wardrobe_sweep"),)),  # A's job
        WardrobePart("styling", observers=(object(),)),  # type: ignore[arg-type]
        WardrobePart("phone", data=(object(),)),  # type: ignore[arg-type]
        WardrobePart("phone", services={"review_writer": RecordingWriter()}),  # B's
    ],
)
def test_the_contract_refuses_what_a_part_does_not_own(part: WardrobePart) -> None:
    with pytest.raises(ValueError, match="part"):
        wiring.check_part(part.name, part)


def test_a_part_must_return_its_own_name() -> None:
    with pytest.raises(ValueError, match="must return"):
        wiring.check_part("catalog", WardrobePart("styling"))
    with pytest.raises(ValueError, match="must return"):
        wiring.check_part("catalog", object())


def test_a_good_part_keeps_its_tools_jobs_services_and_data() -> None:
    store = memory_store(MemoryDocs(), FixedClock(ist(2026, 11, 16)))
    a = WardrobePart(
        "catalog",
        tools=(_tool("wardrobe_find"), _tool("wardrobe_remove")),
        daily_jobs=(RecordingJob("wardrobe_sweep"),),
        services={"store": store},
        ready="ok",
    )
    b = WardrobePart("laundry", daily_jobs=(RecordingJob("laundry_daily"),), data=(_Data(),))
    c = WardrobePart("styling", clock_jobs=(RecordingJob("outfit_clock"),))
    for p in (a, b, c):
        assert wiring.check_part(p.name, p) is p
    app = FastAPI()
    app.state.r13_parts = {"catalog": a, "laundry": b, "styling": c}
    assert [t.name for t in wiring.r13_tools(app.state.r13_parts)] == [
        "wardrobe_find",
        "wardrobe_remove",
    ]
    assert [j.name for j in wiring.r13_tick_jobs(app)] == ["wardrobe_sweep", "laundry_daily"]
    assert [j.name for j in wiring.r13_clock_jobs(app)] == ["outfit_clock"]
    assert wiring.wardrobe_store(app) is store and len(wiring.r13_data(app)) == 1


def test_every_stub_part_builds_through_the_real_modules(settings: Settings) -> None:
    parts = wiring.build_parts(_ctx(settings))
    assert tuple(parts) == PARTS
    assert wiring.SETUP_FAILED not in {p.ready for p in parts.values()}
    assert parts["catalog"].ready == "Off: no document store on this server."
    assert parts["phone"].ready == "ready"


# ---- the joins -----------------------------------------------------------------------------------
async def test_the_store_is_joined_with_bs_writer_and_every_observer_cs_refresh_first() -> None:
    clock = FixedClock(ist(2026, 11, 16, 9, 0))
    store = memory_store(MemoryDocs(), clock)
    writer, refresh, other = RecordingWriter(), RecordingObserver(), RecordingObserver()
    app = FastAPI()
    app.state.r13_parts = {
        "catalog": WardrobePart("catalog", services={"store": store}),
        "laundry": WardrobePart("laundry", services={"review_writer": writer}),
        "styling": WardrobePart("styling", services={"refresh": refresh}),
        "phone": WardrobePart("phone", observers=(other,)),
    }
    wiring.join_store(app)
    assert store._writer is writer  # noqa: SLF001
    assert store._observers == (refresh, other)  # noqa: SLF001


def test_without_part_a_nothing_is_joined_and_nothing_breaks() -> None:
    app = FastAPI()
    wiring.join_store(app)
    wiring.register_bin(app)
    wiring.install_r13_phrases(app)
    assert wiring.wardrobe_store(app) is None and wiring.service(app, "photos") is None


def test_as_bin_restores_and_purges_wardrobe_pieces_in_place() -> None:
    class Bin:
        async def restore(self, uid: str, item: Any, *, outside: bool = False) -> Any: ...

        async def purge(self, uid: str, item: Any) -> None: ...

    registered: list[tuple[str, Any, Any]] = []

    class Undo:
        def register(self, kind: str, restorer: Any, purger: Any = None) -> None:
            registered.append((kind, restorer, purger))

    found = Bin()
    app = FastAPI()
    app.state.undo = Undo()
    app.state.r13_parts = {"catalog": WardrobePart("catalog", services={"bin": found})}
    wiring.register_bin(app)
    assert registered == [("wardrobe_item", found, found)]


def _router(word: str) -> Any:
    def route(text: str, now: datetime) -> NoAIRoute | None:
        return NoAIRoute(reply=word) if word in text else None

    route.__name__ = f"r_{word}"
    return route


def test_add_phrases_can_put_routers_first() -> None:
    mode = BrainMode(Settings(_env_file=None))
    older, newer, first = _router("a"), _router("b"), _router("c")
    mode.add_phrases([older])
    mode.add_phrases([newer])
    mode.add_phrases([first], first=True)
    assert mode.phrases == (first, older, newer)


def test_ds_phrases_go_first_in_their_own_order_ahead_of_r14s(settings: Settings) -> None:
    mode = BrainMode(settings)
    things = _router("things")
    mode.add_phrases([things])  # R14's, installed before R13's
    mine = (_router("wear"), _router("where"), _router("laundry"))
    app = FastAPI()
    app.state.brain_mode = mode
    app.state.r13_parts = {"phone": WardrobePart("phone", services={"phrases": mine})}
    wiring.install_r13_phrases(app)
    wiring.install_r13_phrases(app)  # a second start never adds them twice
    assert mode.phrases == (*mine, things)


def test_a_phrase_that_does_not_fit_is_logged_never_a_stop(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    mode = BrainMode(settings)
    mode.add_phrases([_router(str(i)) for i in range(64)])
    app = FastAPI()
    app.state.brain_mode = mode
    app.state.r13_parts = {"phone": WardrobePart("phone", services={"phrases": (_router("x"),)})}
    wiring.install_r13_phrases(app)
    assert len(mode.phrases) == 64 and "did not fit" in caplog.text


# ---- the real app --------------------------------------------------------------------------------
@asynccontextmanager
async def running(s: Settings) -> AsyncIterator[tuple[FastAPI, AsyncClient]]:
    from jarvis.api import create_app

    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    app.state.wardrobe_now = FixedClock(ist(2026, 11, 16, 10, 0))  # set before the start
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield app, c


async def test_the_app_builds_the_four_parts_and_answers_v1_r13(settings: Settings) -> None:
    async with running(_owner(settings)) as (app, c):
        assert tuple(app.state.r13_parts) == PARTS
        got = await c.get("/v1/r13", headers=AUTH)
        assert got.status_code == 200 and got.headers["cache-control"] == "no-store"
        body = got.json()
        assert body["version"] == "v13.0.0"
        assert [p["part"] for p in body["parts"]] == list(PARTS)
        assert all(p["ready"] != wiring.SETUP_FAILED for p in body["parts"])
        assert body["parts"][0]["ready"].startswith("Off: the wardrobe needs")
        assert (await c.get("/v1/r13")).status_code == 401  # the owner's only


async def test_the_wardrobes_clock_is_the_one_set_before_the_start(settings: Settings) -> None:
    async with running(settings) as (app, _):
        assert app.state.wardrobe_now() == ist(2026, 11, 16, 10, 0)


async def test_wardrobe_off_builds_no_part(settings: Settings) -> None:
    s = settings.model_copy(update={"wardrobe_enabled": False})
    async with running(s) as (app, _):
        assert app.state.r13_parts == {}


async def test_the_restore_gets_its_own_body_cap_and_other_paths_keep_theirs(
    settings: Settings,
) -> None:
    auth = AUTH
    three_mb, past = b"x" * (3 * 1024 * 1024), wiring.RESTORE_BODY_BYTES + 1
    async with running(_owner(settings)) as (_, c):
        for path in wiring.RESTORE_PATHS:
            ok = await c.post(path, content=three_mb, headers=auth)
            assert ok.status_code != 413, path  # past the middleware (A's route answers from A)
            big = await c.post(path, headers=auth | {"content-length": str(past)}, content=b"")
            assert big.status_code == 413, path
        other = await c.post("/v1/wardrobe/scan", content=three_mb, headers=auth)
        assert other.status_code == 413  # every other path keeps the 2.1 MB cap


async def test_his_zone_is_the_brief_stores_else_the_setting(settings: Settings) -> None:
    from jarvis.brief.store import BriefStore

    docs = MemoryDocs()
    zone = wiring.owner_zone(docs, settings)
    assert str(await zone("u")) == settings.user_timezone
    store = BriefStore(docs, prefix=settings.firestore_prefix)
    await store.update_settings("u", lambda cur: cur.model_copy(update={"tz": "Europe/London"}))
    assert str(await zone("u")) == "Europe/London"
    await store.update_settings("u", lambda cur: cur.model_copy(update={"tz": "Not/AZone"}))
    assert str(await zone("u")) == settings.user_timezone


TOKEN = "t" * 32
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _owner(s: Settings) -> Settings:
    """A server that asks for the owner's token (the routes' 401 is real)."""
    from pydantic import SecretStr

    return s.model_copy(update={"env": "prod", "api_token": SecretStr(TOKEN)})


def test_no_wiring_reads_the_real_clock_but_the_wardrobes_default() -> None:
    assert wiring._utcnow().tzinfo is UTC  # noqa: SLF001 - the one real clock, outside wardrobe/


@pytest.mark.parametrize("name", ["store", "photos", "bin", "review_writer", "refresh", "phrases"])
def test_each_named_service_has_one_owner(name: str) -> None:
    from jarvis.wardrobe.ports import SERVICE_OWNER

    assert SERVICE_OWNER[name] in PARTS


def _names(jobs: Sequence[Any]) -> list[str]:
    return [j.name for j in jobs]
