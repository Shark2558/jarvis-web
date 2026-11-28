# src/jarvis/api/r8_wiring.py
"""R8 on the app: I0's skeleton (docs/plans/r8-vision.md v8.0.4 section 7.1, seam S22), completed
at the I1 join (docs/plans/r8-integration/I1-NOTES.md). The builders' parts stay in their own
modules; this one only builds them on `app.state` and joins them to the rest.

- `install_r8_routes(app)`: the coaches' routes (`api/coach.py`), C's day strip
  (`api/coach_day.py`) and B's camera setup (`api/camera_spots.py`).
- `wire_r8(app, s, docs, keyring, now)`: `app.state.coach`, a `CoachApp` over the sealed stores
  (`coach_results`, `coach_people`, `coach_routines` under the keyring's `coach` purpose) and the
  tracking target; None when `coach_enabled` is off. Without a token key the stores answer "off"
  (never in clear).
- `join_r8(app, s, docs)` (after R18, BEFORE the gateway: its tool): `wire_r8`, then
  B's camera setup (`app.state.camera_setup`: the switches and camera health; its home lines from
  the kit's heartbeat, its home cameras from Home's camera settings, every change pushed to the
  laptop), C's screen time and day strip (`coach_screen`, `coach_day`), J's `HomeLive` on
  `coach.home` (its reader: B's switches and the target store, the durable truth; a target change
  is pushed too), the Faces lookup for "track <name>" (`coach.lookup`), and on Home's webhook
  the coach reports' handler (HomeLive, then C's posture nudge for "me" only) and the coach part
  of the state. A part whose inputs are off is None; nothing here makes a network call.
- `LateCameras`, `LateScreen`: Vitals' two R8 readers (Vitals is wired at R4, before R8).
- `r8_privacy_sources(app)`: Privacy's "Health and fitness" rows, then B's camera setup row.
- `coach_tools(app)` / `r8_tools(app, names)`: the brain's `coach_results` (R1).
- `r8_brief(app)`: C's one line in the brief's Helpers section. `r8_tick_jobs(app)`: the sweep.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI

from jarvis.api.camera_spots import CameraSetupApp, build_camera_setup
from jarvis.api.camera_spots import router as camera_router
from jarvis.api.coach import CoachApp
from jarvis.api.coach import router as coach_router
from jarvis.api.coach_day import router as day_router
from jarvis.camera.health import camera_setup_privacy
from jarvis.camera.spots import Spots, home_uses
from jarvis.coach.brief import CoachDayBrief
from jarvis.coach.day import DayService
from jarvis.coach.live import HomeLive, Wanted
from jarvis.coach.people import ME, PeopleStore
from jarvis.coach.privacy import coach_privacy
from jarvis.coach.screentime import BridgeScreenTime
from jarvis.coach.store import CoachStore, RoutineStore
from jarvis.coach.target import TargetStore, TrackTarget
from jarvis.coach.tools import results_tool
from jarvis.coach.usecases import USE_CASES
from jarvis.config import Settings
from jarvis.helpers.nudges.posture import PostureNudger, on_report
from jarvis.home.ports import CoachReport
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.privacy.sources import CallbackSource
from jarvis.storage.docs import Docs
from jarvis.tools.base import Tool

log = get_logger(__name__)

ROUTERS = (coach_router, day_router, camera_router)
# The home camera's coaches that run while a home camera is set for the desk (the Desk pane's
# words: "Runs on the home laptop when the home camera is set for the desk"): posture, activity,
# seated and bp-posture (`jarvis.coach.usecases`, source "home", spot "desk").
DESK_HOME_USES: tuple[str, ...] = tuple(
    u.id for u in USE_CASES if u.source == "home" and u.spot == "desk"
)
SWEEP_JOB = "coach_sweep"
SWEEP_BUDGET_S = 20.0
Names = Callable[[str], Awaitable[Mapping[str, str]]]


def install_r8_routes(app: FastAPI) -> None:
    for router in ROUTERS:
        app.include_router(router)


def wire_r8(
    app: FastAPI,
    s: Settings,
    docs: Docs,
    keyring: Keyring | None,
    now: Callable[[], datetime],
) -> CoachApp | None:
    if not s.coach_enabled:
        app.state.coach = None
        return None
    prefix, tz = s.firestore_prefix, s.user_timezone
    coach = CoachApp(
        store=CoachStore(docs, keyring, prefix=prefix, now=now, tz=tz, keep_days=s.coach_keep_days),
        people=PeopleStore(docs, keyring, prefix=prefix, now=now),
        target=PushedTarget(docs, prefix=prefix, now=now),
        routines=RoutineStore(docs, keyring, prefix=prefix, now=now),
    )
    app.state.coach = coach
    return coach


# ---- the coach part of the bridge's state (J), from B's switches and the target --------------
class PushedTarget(TargetStore):
    """The target store; each change is pushed to the home laptop (`HomeLive.push`), best effort."""

    on_change: Callable[[str], Awaitable[None]] | None = None

    async def set(self, uid: str, target: TrackTarget) -> TrackTarget:
        saved = await super().set(uid, target)
        if self.on_change is not None:
            try:
                await self.on_change(uid)
            except Exception as exc:  # noqa: BLE001 - saved; the next heartbeat catches up
                log.warning("tracking target not pushed", extra={"error": type(exc).__name__})
        return saved


def wanted_of(spots: Spots, target: TrackTarget) -> Wanted:
    """What runs on which home camera: the desk coaches on each home camera set for the desk
    that may look now (B's `home_uses`: none after "cameras off"), the target, "cameras off"."""
    desk = {c.id: DESK_HOME_USES for c in spots.cameras if c.kind == "home" and c.spot == "desk"}
    return Wanted.of(home_uses(spots, desk), target, spots.all_off)


class CoachSwitches:
    """HomeLive's reader and push: B's sealed switches and the target store, read each time."""

    def __init__(self, setup: CameraSetupApp, target: TargetStore) -> None:
        self._setup, self._target = setup, target
        self.live: HomeLive | None = None

    async def read(self, uid: str) -> Wanted | None:
        try:
            return wanted_of(await self._setup.spots.get(uid), await self._target.get(uid))
        except Exception as exc:  # noqa: BLE001 - unreadable: HomeLive uses the last push
            log.warning("coach switches unreadable", extra={"error": type(exc).__name__})
            return None

    async def push(self, uid: str, spots: Spots | None = None) -> None:
        if self.live is None:
            return
        found = wanted_of(spots, await self._target.get(uid)) if spots is not None else None
        wanted = found or await self.read(uid)
        if wanted is None:
            return
        target = TrackTarget(kind=wanted.target, person=wanted.person)  # type: ignore[arg-type]
        await self.live.push(uid, uses=dict(wanted.uses), target=target, all_off=wanted.all_off)


class CoachReports:
    """Home's webhook handler for "coach" events: J's HomeLive first (views, tallies), then C's
    posture nudge, which only ever nudges him ("me") and never fails the event."""

    handles = frozenset({"coach"})

    def __init__(self, live: HomeLive, nudger: PostureNudger | None, read: CoachSwitches) -> None:
        self._live, self._nudger, self._read = live, nudger, read

    async def handle(self, uid: str, event: Any) -> None:
        await self._live.handle(uid, event)
        if self._nudger is None or not isinstance(event, CoachReport) or event.who != ME:
            return
        wanted = await self._read.read(uid)
        if wanted is not None and not wanted.on(event.camera, event.use):
            return
        try:
            await on_report(self._nudger, uid, event)
        except Exception as exc:  # noqa: BLE001 - a nudge never makes the bridge resend a report
            log.warning("posture nudge failed", extra={"error": type(exc).__name__})


# ---- the faces lookup ("track <name>") and the tool's names -----------------------------------
class FacesLookup:
    """`PeopleLookup` over R3's faces: the fp_ id of the one enrolled, consented person by that
    name (any case), else None. Never a picture or an embedding."""

    def __init__(self, faces: Any) -> None:
        self._faces = faces

    async def find(self, uid: str, name: str) -> str | None:
        want = " ".join(str(name).split()).casefold()
        try:
            state = await self._faces.state(uid)
        except Exception as exc:  # noqa: BLE001 - unreadable: nobody is found
            log.warning("faces unreadable for a name", extra={"error": type(exc).__name__})
            return None
        found = [p.id for p in state.people if p.naming and p.name.casefold() == want]
        return found[0] if len(found) == 1 else None


def tool_names(app: FastAPI) -> Names:
    """{who: the name he knows them by}: you, his guests' labels, his enrolled people's names."""

    async def names(uid: str) -> Mapping[str, str]:
        st, out = app.state, {ME: "you"}
        coach: CoachApp | None = getattr(st, "coach", None)
        try:
            if coach is not None:
                out.update({g.id: g.label for g in await coach.people.guests(uid)})
            faces = getattr(st, "faces", None)
            if faces is not None:
                out.update({p.id: p.name for p in (await faces.state(uid)).people if p.naming})
        except Exception as exc:  # noqa: BLE001 - the numbers still go out, as "Guest"
            log.warning("coach names unreadable", extra={"error": type(exc).__name__})
        return out

    return names


# ---- the join -----------------------------------------------------------------------------------
def _home_seen(app: FastAPI) -> Callable[[str], Awaitable[Mapping[str, float]]]:
    """Home camera id -> when the kit last said it was producing frames (its heartbeat)."""

    async def seen(uid: str) -> Mapping[str, float]:
        store = getattr(app.state, "home_store", None)
        status = await store.status(uid) if store is not None else None
        if status is None or status.last_seen_at is None:
            return {}
        cams = status.parts.get("cameras") or []
        return {
            str(c["id"]): float(status.last_seen_at)
            for c in cams
            if isinstance(c, dict) and c.get("online") is True and "id" in c
        }

    return seen


def _home_cameras(app: FastAPI) -> Callable[[str], Awaitable[Mapping[str, str]]]:
    """The home kit's camera ids -> his labels (Home's camera settings)."""

    async def cameras(uid: str) -> Mapping[str, str]:
        camera = getattr(app.state, "camera", None)
        if camera is None:
            return {}
        return {cid: c.label for cid, c in (await camera.config.get(uid)).cameras.items()}

    return cameras


def _camera_setup(
    app: FastAPI, s: Settings, docs: Docs, ring: Keyring | None, switches: list[CoachSwitches]
) -> CameraSetupApp | None:
    st = app.state
    found = getattr(st, "camera_setup", None)
    if isinstance(found, CameraSetupApp):
        return found  # a host (the browser tests) set its own before startup

    async def changed(uid: str, spots: Spots) -> None:
        for sw in switches:
            await sw.push(uid, spots)

    camera = getattr(st, "camera", None)
    return build_camera_setup(
        docs,
        ring,
        prefix=s.firestore_prefix,
        caller=getattr(st, "home_client", None),
        arm=camera.alarm if camera is not None else None,
        home_cameras=_home_cameras(app),
        home_seen=_home_seen(app),
        on_change=changed,
    )


def _nudger(app: FastAPI) -> PostureNudger | None:
    parts = getattr(app.state, "r11_parts", None) or {}
    part = parts.get("nudges")
    svc = part.services.get("service") if part is not None else None
    return PostureNudger(svc) if svc is not None else None


def join_r8(app: FastAPI, s: Settings, docs: Docs) -> None:
    """Every R8 part on `app.state` (see the module's words); None where its inputs are off."""
    st = app.state
    ring = Keyring.from_settings(s)
    switches: list[CoachSwitches] = []
    st.camera_setup = setup = _camera_setup(app, s, docs, ring, switches)
    coach = wire_r8(app, s, docs, ring, lambda: datetime.now(UTC))
    caller = getattr(st, "home_client", None)
    st.coach_screen = st.coach_day = None
    if coach is None:
        return
    st.coach_screen = BridgeScreenTime(caller, tz=s.user_timezone, clock=time.time)
    st.coach_day = DayService(
        coach.store, st.coach_screen, tz=s.user_timezone, now=lambda: datetime.now(UTC)
    )
    faces = getattr(st, "faces", None)
    coach.lookup = FacesLookup(faces) if faces is not None else None
    if setup is None:
        return  # no token key: no switches to follow, so no home views either
    sw = CoachSwitches(setup, coach.target)
    live = HomeLive(coach.store, coach.people, caller=caller, reader=sw.read)
    sw.live, coach.home = live, live
    switches.append(sw)
    if isinstance(coach.target, PushedTarget):
        coach.target.on_change = sw.push
    hook = getattr(st, "home_webhook", None)
    if hook is not None:
        hook.join(CoachReports(live, _nudger(app), sw), live)


# ---- Vitals (wired at R4, before R8): read late ------------------------------------------------
class LateCameras:
    """`OwnSources.cameras`: B's camera health, one line per camera (none when not wired)."""

    def __init__(self, app: FastAPI) -> None:
        self._app = app

    async def lines(self, uid: str) -> Sequence[Any]:
        setup = getattr(self._app.state, "camera_setup", None)
        return await setup.health.lines(uid) if isinstance(setup, CameraSetupApp) else []


class LateScreen:
    """`OwnSources.screen`: C's screen time through the home bridge ("not_installed" when off)."""

    def __init__(self, app: FastAPI) -> None:
        self._app = app

    async def state(self, uid: str) -> str:
        screen = getattr(self._app.state, "coach_screen", None)
        return "not_installed" if screen is None else str(await screen.state(uid))


# ---- privacy, the tool, the brief, the sweep ----------------------------------------------------
def r8_privacy_sources(app: FastAPI) -> tuple[CallbackSource, ...]:
    coach = getattr(app.state, "coach", None)
    rows = coach_privacy(coach.store, coach.people) if isinstance(coach, CoachApp) else ()
    setup = getattr(app.state, "camera_setup", None)
    if isinstance(setup, CameraSetupApp):
        rows = (*rows, camera_setup_privacy(setup.spots, setup.health))
    return tuple(rows)


def r8_tools(app: FastAPI, names: Names) -> list[Tool]:
    coach = getattr(app.state, "coach", None)
    return [results_tool(coach.store, names)] if isinstance(coach, CoachApp) else []


def coach_tools(app: FastAPI) -> list[Tool]:
    """For `build_gateway(r8=...)`: the coach tool with the names he knows people by."""
    return r8_tools(app, tool_names(app))


def r8_brief(app: FastAPI) -> tuple[CoachDayBrief, ...]:
    days = getattr(app.state, "coach_day", None)
    return (CoachDayBrief(days),) if isinstance(days, DayService) else ()


class CoachSweep:
    """The morning tick's sweep: kept results older than `coach_keep_days` go."""

    name = SWEEP_JOB
    budget_s = SWEEP_BUDGET_S

    def __init__(self, store: CoachStore) -> None:
        self._store = store

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        swept = failed = 0
        for uid in owners:
            try:
                swept += await self._store.sweep(uid)
            except Exception as exc:  # noqa: BLE001 - one owner's failure never stops the rest
                failed += 1
                log.warning("coach sweep failed", extra={"error": type(exc).__name__})
        return {"swept": swept, "failed": failed}


def r8_tick_jobs(app: FastAPI) -> tuple[CoachSweep, ...]:
    """The sweep, only when results can be kept (the token key): unsealed, nothing is kept."""
    coach = getattr(app.state, "coach", None)
    return (CoachSweep(coach.store),) if isinstance(coach, CoachApp) and coach.store.sealed else ()


__all__ = [
    "DESK_HOME_USES",
    "ROUTERS",
    "CoachReports",
    "CoachSweep",
    "CoachSwitches",
    "FacesLookup",
    "LateCameras",
    "LateScreen",
    "PushedTarget",
    "coach_tools",
    "install_r8_routes",
    "join_r8",
    "r8_brief",
    "r8_privacy_sources",
    "r8_tick_jobs",
    "r8_tools",
    "tool_names",
    "wanted_of",
    "wire_r8",
]
