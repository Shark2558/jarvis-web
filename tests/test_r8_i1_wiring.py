# tests/test_r8_i1_wiring.py -- R8 I1 join (docs/plans/r8-integration/I1-NOTES.md): the app
# joins every R8 part. On a real app's startup (mock brain): the coaches (`app.state.coach`) with
# J's HomeLive and the Faces lookup, B's camera setup, C's screen time and day strip; the coach
# reports' handler and the coach part of the state on Home's webhook; Privacy's rows, the brain's
# tool, Vitals' two readers, the brief's line and the sweep. Then each join on its own: the
# switches pushed to the laptop (B's change, a target change), the posture nudge for him only, the
# faces lookup, the sweep. Without a token key nothing is kept and the routes say why.
from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

import jarvis.api.r8_wiring as W
from jarvis.api import create_app
from jarvis.api.camera_spots import CameraSetupApp, build_camera_setup
from jarvis.api.r11_wiring import helpers_brief
from jarvis.api.tick_wiring import tick_jobs
from jarvis.camera.spots import Camera, Room, Spots
from jarvis.coach.brief import CoachDayBrief
from jarvis.coach.day import DayService
from jarvis.coach.live import HomeLive
from jarvis.coach.people import PeopleStore
from jarvis.coach.screentime import BridgeScreenTime
from jarvis.coach.store import CoachStore
from jarvis.coach.target import TrackTarget
from jarvis.coach.words import POSTURE_NUDGE
from jarvis.config import Settings
from jarvis.home.ports import CoachReport
from jarvis.keyring import Keyring
from jarvis.llm.mock_provider import MockProvider
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage.docs import MemoryDocs

ROOT_KEY = bytes(range(91, 123))  # a made-up token key
KEY = SecretStr(base64.b64encode(ROOT_KEY).decode())
UID = "u1"
NOW = 1764300000.0


@asynccontextmanager
async def running(s: Settings) -> AsyncIterator[tuple[FastAPI, AsyncClient]]:
    app = create_app(s, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield app, c


def sealed(settings: Settings, **over: Any) -> Settings:
    return settings.model_copy(update={"token_key": KEY, **over})


# ---- the whole app ------------------------------------------------------------------------------
async def test_the_app_joins_every_r8_part(settings: Settings) -> None:
    async with running(sealed(settings)) as (app, c):
        st = app.state
        assert isinstance(st.coach.home, HomeLive) and isinstance(st.coach.lookup, W.FacesLookup)
        assert isinstance(st.camera_setup, CameraSetupApp)
        assert isinstance(st.coach_screen, BridgeScreenTime) and isinstance(
            st.coach_day, DayService
        )
        hook = st.home_webhook
        assert any(isinstance(h, W.CoachReports) for h in hook._handlers)  # noqa: SLF001
        assert st.coach.home in hook._sources  # noqa: SLF001 - the coach part of the state
        ids = set(st.privacy.registry.ids())
        assert {"coach_me", "coach_people", "coach_guests", "camera_setup"} <= ids
        assert "coach_results" in {t.name for t in st.gateway.registry.specs()}
        brief = helpers_brief(app)
        assert brief is not None
        assert any(isinstance(x, CoachDayBrief) for x in brief._contributors())  # noqa: SLF001
        assert "coach_sweep" in {j.name for j in tick_jobs(app)}
        for path in ("/v1/coach/day", "/v1/camera/spots", "/v1/coach/live?use=posture"):
            r = await c.get(path)
            assert r.status_code == 200, (path, r.text)
        assert (await c.get("/v1/coach/live?use=posture")).json()["bodies"] == []


async def test_vitals_read_the_camera_lines_and_screen_time_late(settings: Settings) -> None:
    from jarvis.api.selfcheck_wiring import vitals_sources

    async with running(sealed(settings)) as (app, _):
        own = vitals_sources(app)
        assert isinstance(own.cameras, W.LateCameras) and isinstance(own.screen, W.LateScreen)
        assert await own.cameras.lines(UID) == []  # no camera registered yet
        assert await own.screen.state(UID) in ("ok", "not_installed", "unreachable")
        app.state.coach_screen = None
        assert await own.screen.state(UID) == "not_installed"


async def test_without_a_token_key_nothing_is_kept_and_the_routes_say_why(
    settings: Settings,
) -> None:
    async with running(settings) as (app, c):
        assert app.state.camera_setup is None and app.state.coach.home is None
        r = await c.get("/v1/camera/spots")
        assert r.status_code == 404 and r.json()["error"] == "cameras_off"
        assert (await c.get("/v1/coach/live?use=posture")).status_code == 501
        assert "camera_setup" not in set(app.state.privacy.registry.ids())


async def test_coaches_off_in_settings_leave_the_camera_setup_on(settings: Settings) -> None:
    async with running(sealed(settings, coach_enabled=False)) as (app, c):
        assert app.state.coach is None and app.state.coach_day is None
        assert isinstance(app.state.camera_setup, CameraSetupApp)
        assert (await c.get("/v1/camera/spots")).status_code == 200
        assert W.r8_tick_jobs(app) == () and W.r8_brief(app) == ()


# ---- the joins on their own --------------------------------------------------------------------
def _now() -> datetime:
    return datetime.fromtimestamp(NOW, UTC)


class Caller:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    async def call(
        self, uid: str, method: str, path: str, body: Any = None, *, query: Any = None
    ) -> dict[str, Any]:
        self.calls.append((method, path, body))
        return {}


def _spots(*, spot: str = "desk", all_off: bool = False, never: bool = False) -> Spots:
    return Spots(
        rev=0,
        cameras=(
            Camera(
                id="desk_cam", kind="home", source="home", label="Desk", spot=spot, room="study"
            ),  # type: ignore[arg-type]  # fmt: skip
            Camera(id="webcam", kind="device", source="browser", label="Laptop", spot="desk"),
        ),
        rooms=(Room(id="study", label="Study", never=never),),
        all_off=all_off,
    )


def test_the_desk_coaches_run_on_a_home_camera_set_for_the_desk_only() -> None:
    everyone = TrackTarget()
    on = W.wanted_of(_spots(), everyone)
    assert dict(on.uses) == {"desk_cam": ("posture", "activity", "seated", "bp-posture")}
    assert W.DESK_HOME_USES == ("posture", "activity", "seated", "bp-posture")
    assert dict(W.wanted_of(_spots(spot="workout"), everyone).uses) == {}
    off = W.wanted_of(_spots(all_off=True), everyone)
    assert dict(off.uses) == {} and off.all_off is True  # "cameras off": nothing runs
    assert dict(W.wanted_of(_spots(never=True), everyone).uses) == {}  # a "never" room
    me = W.wanted_of(_spots(), TrackTarget(kind="me"))
    assert me.target == "me" and me.person is None


def _rig(caller: Caller | None = None) -> tuple[Any, ...]:
    docs, ring = MemoryDocs(), Keyring(ROOT_KEY)
    setup = build_camera_setup(docs, ring, caller=caller)
    assert setup is not None
    store = CoachStore(docs, ring, now=_now)
    people = PeopleStore(docs, ring, now=_now)
    target = W.PushedTarget(docs, now=_now)
    sw = W.CoachSwitches(setup, target)
    live = HomeLive(store, people, caller=caller, reader=sw.read, clock=lambda: NOW)
    sw.live = live
    target.on_change = sw.push
    return setup, store, people, target, sw, live


async def test_a_change_of_switches_or_target_is_pushed_to_the_laptop() -> None:
    caller = Caller()
    setup, _, _, target, sw, _ = _rig(caller)
    await sw.push(UID, _spots())  # B's on_change after a saved change
    (method, path, body) = caller.calls[-1]
    assert (method, path) == ("POST", "/bridge/v1/state")
    assert body["coach"]["uses"] == {"desk_cam": ["posture", "activity", "seated", "bp-posture"]}
    assert "arm" not in body and "armed" not in str(body)  # never the alarm (D11)
    await setup.spots.put(UID, _spots(), base_rev=0)
    await target.set(UID, TrackTarget(kind="me"))
    assert caller.calls[-1][2]["coach"]["target"] == "me"


class Nudger:
    def __init__(self) -> None:
        self.asked: list[float] = []

    async def slouched(self, uid: str, *, held_s: float, at: float) -> bool:
        self.asked.append(held_s)
        return True


def _report(
    who: str, *, use: str = "posture", camera: str = "desk_cam", track: int = 1
) -> CoachReport:
    tip = {"kind": "tip", "text": POSTURE_NUDGE, "since": int(NOW) - 70, "held": 70}
    return CoachReport(type="coach", id="e" + (who or "g")[:8].replace("_", "x"), at=NOW,
                       camera=camera, use=use, session="cs_0123456789ab", track=track, who=who,
                       view=({"kind": "line", "text": "Slouching"}, tip))  # fmt: skip


async def test_the_joined_handler_nudges_him_only_and_keeps_everyones_view() -> None:
    setup, _, _, _, sw, live = _rig()
    await setup.spots.put(UID, _spots(), base_rev=0)
    nudger = Nudger()
    handler = W.CoachReports(live, nudger, sw)  # type: ignore[arg-type]
    for track, who in ((2, ""), (3, "fp_0123456789ab")):
        await handler.handle(UID, _report(who, track=track))
    assert nudger.asked == []  # a guest and an enrolled person: never nudged
    await handler.handle(UID, _report("me", camera="other_cam"))
    assert nudger.asked == []  # a camera whose coach is off: nothing
    await handler.handle(UID, _report("me"))
    assert nudger.asked == [70.0]
    assert sorted(b["who"] for b in live.live(UID, "posture")) == ["", "fp_0123456789ab", "me"]


async def test_a_failing_nudge_never_fails_the_report() -> None:
    setup, _, _, _, sw, live = _rig()
    await setup.spots.put(UID, _spots(), base_rev=0)

    class Broken(Nudger):
        async def slouched(self, uid: str, *, held_s: float, at: float) -> bool:
            raise RuntimeError("the gate is down")

    await W.CoachReports(live, Broken(), sw).handle(UID, _report("me"))  # type: ignore[arg-type]
    assert [b["who"] for b in live.live(UID, "posture")] == ["me"]


class Person:
    def __init__(self, pid: str, name: str, naming: bool = True) -> None:
        self.id, self.name, self.naming = pid, name, naming


class Faces:
    def __init__(self, *people: Person) -> None:
        self.people = people

    async def state(self, uid: str) -> Any:
        return self


async def test_track_a_name_finds_one_consented_person_only() -> None:
    ana, bob = Person("fp_aaaaaaaaaaaa", "Ana"), Person("fp_bbbbbbbbbbbb", "Bob", naming=False)
    look = W.FacesLookup(Faces(ana, bob))
    assert await look.find(UID, "  ana ") == "fp_aaaaaaaaaaaa"
    assert await look.find(UID, "Bob") is None  # not enrolled with consent
    twins = W.FacesLookup(Faces(ana, Person("fp_cccccccccccc", "ANA")))
    assert await twins.find(UID, "Ana") is None  # two by that name: nobody is guessed


async def test_the_sweep_runs_for_each_owner_and_counts_failures() -> None:
    _, store, *_ = _rig()

    class Bad(CoachStore):
        async def sweep(self, uid: str) -> int:
            raise RuntimeError("down")

    assert await W.CoachSweep(store).run([UID, "u2"]) == {"swept": 0, "failed": 0}
    assert (await W.CoachSweep(Bad(MemoryDocs(), None, now=_now)).run([UID]))["failed"] == 1


def test_the_kit_carries_the_four_home_rules_and_says_it_is_newer() -> None:
    import io
    import zipfile

    from jarvis.coach.home import REGISTRY
    from jarvis.home import kit
    from jarvis.homebridge.config import BRIDGE_VERSION

    assert sorted(REGISTRY) == ["activity", "bp-posture", "posture", "seated"]
    names = set(zipfile.ZipFile(io.BytesIO(kit.build("https://jarvis.example.app"))).namelist())
    for rule in ("posture", "activity", "seated", "bp_posture"):
        assert f"JARVIS-Home/bridge-src/jarvis/coach/home/{rule}.py" in names, rule
    assert BRIDGE_VERSION == kit.KIT_VERSION == "0.3.0"
    assert kit.outdated("0.2.0")  # an R11.1 bridge is told to update its kit
