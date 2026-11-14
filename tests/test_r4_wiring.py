# tests/test_r4_wiring.py -- R4 I1: the app wires vitals, the systems check, the connectors, people
# research and the ONE no-AI switch (api/r4_wiring.py). With defaults everything starts; each
# feature is OFF with plain words when its dependency is missing and ON when it is there; the Brain
# and the routes share the same BrainMode object; the tick carries vitals_poll and health_check;
# the health probes are built only for the integrations that exist; no-AI mode routes a systems
# check through the registered tool.
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.routing import iter_route_contexts
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from r3_app import UID, H, r3_app, r3_settings

from jarvis.api import create_app
from jarvis.api.personal import RESERVED_JOB_NAMES
from jarvis.api.r4_wiring import R4_STATE, FacesAndPhotosPrivacy, LiveHealth, voice_allowances
from jarvis.config import Settings
from jarvis.llm.fallback import OFFLINE_TOOLS
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.offline.mode import BrainMode
from jarvis.photos.tools import ConnectorDeps
from jarvis.ticks import run_jobs

ALWAYS_ON = {"vitals_show", "vitals_set_key", "vitals_delete_key", "systems_check"}
GITHUB_TOOLS = {"connect_github", "github_profile", "github_repos", "github_activity"}
CONNECTED_ONLY = {"connect_youtube", "youtube_own_channel", "photos_import"}
PEOPLE_TOOLS = {"research_person", "people_open_profiles"}
R4_ROUTES = (
    "/v1/vitals",
    "/v1/vitals/keys",
    "/v1/health",
    "/v1/health/run",
    "/v1/health/speak",
    "/v1/connectors",
    "/v1/connectors/github",
    "/v1/connectors/photos/start",
    "/v1/people/research",
    "/v1/people/last",
    "/v1/settings/brain-mode",
)

# R11 I0: on every tick, no key needed; R7's own two after them (I1 fixer)
R11_JOBS = ("helpers_clock", "helpers_daily", "mobile_clock", "mobile_daily")


@dataclass
class App:
    app: Any
    client: AsyncClient

    @property
    def state(self) -> Any:
        return self.app.state

    def tools(self) -> set[str]:
        return {t.name for t in self.state.gateway.registry.specs()}


@asynccontextmanager
async def plain_app(s: Settings) -> AsyncIterator[App]:
    """The app with the DEFAULT settings (no token key, no Google, no Telegram, no web key)."""
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield App(app, c)


# ---- start-up with defaults ----------------------------------------------------------------------


async def test_defaults_start_and_every_r4_state_name_is_set(settings: Settings) -> None:
    async with plain_app(settings) as a:
        for name in R4_STATE:
            assert hasattr(a.state, name), name
        assert isinstance(a.state.brain_mode, BrainMode)
        assert a.state.vitals is not None and a.state.health is not None
        # OFF until connected: no encryption key, no Google link, no home kit, no web key
        assert a.state.github is None and a.state.youtube_own is None and a.state.photos is None
        assert a.state.people is None
        assert a.state.connectors == ConnectorDeps(None, None, None)


async def test_brain_and_app_share_the_one_brain_mode_object(settings: Settings) -> None:
    async with plain_app(settings) as a:
        assert a.state.brain.mode is a.state.brain_mode
        r = await a.client.get("/v1/settings/brain-mode")
        assert r.status_code == 200 and r.json()["mode"] == "ai"
        r = await a.client.post("/v1/settings/brain-mode", json={"mode": "none"}, headers=H)
        assert r.status_code == 200, r.text
        assert a.state.brain.mode.current == "none"  # the Brain saw the flip: same object


async def test_always_on_tools_are_registered_and_connected_ones_are_not(
    settings: Settings,
) -> None:
    async with plain_app(settings) as a:
        names = a.tools()
        assert ALWAYS_ON <= names
        assert not (GITHUB_TOOLS | CONNECTED_ONLY | PEOPLE_TOOLS) & names
        # offline mode's small model never gets any of them
        assert not (ALWAYS_ON | GITHUB_TOOLS | CONNECTED_ONLY | PEOPLE_TOOLS) & set(OFFLINE_TOOLS)


async def test_tick_carries_vitals_poll_and_health_check_with_unique_names(
    settings: Settings,
) -> None:
    async with plain_app(settings) as a:
        names = [j.name for j in a.state.tick_jobs]
        assert names == ["vitals_poll", "health_check", *R11_JOBS]
        assert not RESERVED_JOB_NAMES & set(names)
        assert await run_jobs(a.state.tick_jobs, [UID]) == dict.fromkeys(names, "ok")


async def test_every_r4_route_is_mounted_and_authed(settings: Settings) -> None:
    async with plain_app(settings) as a:
        paths = {str(rc.path) for rc in iter_route_contexts(a.app.routes)}
        for path in R4_ROUTES:
            assert path in paths, path
        board = await a.client.get("/v1/vitals")
        assert board.status_code == 200, board.text
        health = await a.client.get("/v1/health")
        assert health.status_code == 200 and health.json()["systems"] == []
        connectors = await a.client.get("/v1/connectors")
        assert connectors.status_code == 200
        assert connectors.json()["github"]["connected"] is False
        people = await a.client.post(
            "/v1/people/research", json={"name": "Ada Lovelace"}, headers=H
        )
        assert people.status_code == 503  # people research is OFF without a web key


async def test_health_probes_with_defaults_are_only_the_brain_and_the_documents(
    settings: Settings,
) -> None:
    async with plain_app(settings) as a:
        keys = [p.key for p in a.state.health._probes]  # noqa: SLF001
        assert keys == ["brain", "docs"]
        r = await a.client.post("/v1/health/run", headers=H)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["overall"] == "ok" and {s["key"] for s in body["systems"]} == {"brain", "docs"}
        assert "nominal" in body["spoken"]


async def test_the_brief_carries_the_vitals_section_maker(settings: Settings) -> None:
    async with plain_app(settings) as a:
        assert a.state.brief._vitals is not None  # noqa: SLF001


async def test_no_ai_mode_answers_a_systems_check_through_the_registered_tool(
    settings: Settings,
) -> None:
    async with plain_app(settings) as a:
        assert (
            await a.client.post("/v1/settings/brain-mode", json={"mode": "none"}, headers=H)
        ).status_code == 200
        r = await a.client.post("/v1/chat", json={"message": "run a systems check"})
        assert r.status_code == 200, r.text
        assert "systems" in r.json()["reply"].lower()
        r = await a.client.post("/v1/chat", json={"message": "draft an email to my boss"})
        assert r.status_code == 200
        assert "needs the AI switched on" in r.json()["reply"]


# ---- OFF by flag -------------------------------------------------------------------------------


async def test_vitals_switched_off_leaves_no_tool_route_or_job(settings: Settings) -> None:
    async with plain_app(settings.model_copy(update={"vitals_enabled": False})) as a:
        assert a.state.vitals is None
        assert not {"vitals_show", "vitals_set_key"} & a.tools()
        assert [j.name for j in a.state.tick_jobs] == ["health_check", *R11_JOBS]
        assert (await a.client.get("/v1/vitals")).status_code == 503
        assert a.state.brief._vitals is None  # noqa: SLF001


async def test_health_switched_off_leaves_no_tool_route_or_job(settings: Settings) -> None:
    async with plain_app(settings.model_copy(update={"health_enabled": False})) as a:
        assert a.state.health is None
        assert "systems_check" not in a.tools()
        assert [j.name for j in a.state.tick_jobs] == ["vitals_poll", *R11_JOBS]
        r = await a.client.get("/v1/health")
        assert r.status_code == 503 and "not available" in r.text
        assert (await a.client.post("/v1/health/run", headers=H)).status_code == 503


async def test_people_research_switched_off_even_with_a_web_key(settings: Settings) -> None:
    s = settings.model_copy(
        update={"people_research_enabled": False, "tavily_api_key": SecretStr("tvly-test")}
    )
    async with plain_app(s) as a:
        assert a.state.web is not None and a.state.people is None
        assert not PEOPLE_TOOLS & a.tools()


# ---- ON when the dependency exists -------------------------------------------------------------


async def test_with_the_token_key_github_is_on_and_photos_waits_for_google() -> None:
    async with r3_app() as w:
        st = w.state
        assert st.github is not None  # the keyring seals the token
        assert st.photos is None  # no Google link yet: OFF, plain words from the route
        assert st.connectors.github is st.github and st.connectors.photos is None
        names = {t.name for t in st.gateway.registry.specs()}
        assert GITHUB_TOOLS <= names and ALWAYS_ON <= names
        assert "photos_import" not in names and "youtube_own_channel" not in names
        r = await w.client.post("/v1/connectors/photos/start", headers=H)
        assert r.status_code in (503, 409), r.text


async def test_health_probes_follow_the_integrations_that_exist() -> None:
    async with r3_app() as w:  # Telegram paired, a home linked, no Google, no web key
        keys = [p.key for p in w.state.health._probes]  # noqa: SLF001
        assert keys == ["brain", "docs", "telegram", "home"]


async def test_people_research_is_on_with_a_web_key(settings: Settings) -> None:
    s = settings.model_copy(update={"tavily_api_key": SecretStr("tvly-test")})
    async with plain_app(s) as a:
        assert a.state.people is not None
        assert PEOPLE_TOOLS <= a.tools()


async def test_people_research_is_a_privacy_category_and_faces_stays_last(
    settings: Settings,
) -> None:
    s = settings.model_copy(update={"tavily_api_key": SecretStr("tvly-test")})
    async with plain_app(s) as a:
        ids = a.state.privacy.registry.ids()
        assert "people_research" in ids and ids[-1] == "faces"


async def test_a_part_that_fails_to_build_is_off_not_fatal(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import jarvis.api.r4_wiring as wiring

    def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("store down")

    monkeypatch.setattr(wiring, "wire_vitals", boom)
    async with plain_app(settings) as a:
        assert a.state.vitals is None and a.state.health is not None


async def test_the_github_client_is_closed_on_shutdown() -> None:
    async with r3_app() as w:
        gh = w.state.github
    assert gh._http.is_closed  # noqa: SLF001


# ---- small parts -------------------------------------------------------------------------------


def test_voice_allowances_name_every_voice_price(settings: Settings) -> None:
    specs = voice_allowances(settings)
    assert [s.label for s in specs] == ["Voice (Chirp 3 HD)", "Voice (Studio)", "Speech to text"]
    assert all(s.free_units > 0 for s in specs)


async def test_live_health_answers_503_before_the_service_exists() -> None:
    from fastapi import FastAPI, HTTPException

    app = FastAPI()
    with pytest.raises(HTTPException) as exc:
        await LiveHealth(app).last(UID)
    assert exc.value.status_code == 503


async def test_faces_delete_all_also_purges_the_photos_state() -> None:
    purged: list[str] = []

    class Faces:
        async def remove_all(self, uid: str) -> int:
            return 2

    class Photos:
        async def purge(self, uid: str) -> None:
            purged.append(uid)

    src = FacesAndPhotosPrivacy(Faces(), Photos())  # type: ignore[arg-type]
    assert await src.delete(UID) == 2 and purged == [UID]
    assert await FacesAndPhotosPrivacy(None, None).delete(UID) == 0
    assert purged == [UID]  # nothing wired: nothing to purge, no error


def test_r3_settings_keep_r4_defaults_on() -> None:
    s = r3_settings()
    assert s.vitals_enabled and s.health_enabled and s.photos_enabled
    assert s.people_research_enabled and s.brain_mode == "ai"
