# src/jarvis/api/r8_wiring.py
"""R8 on the app: the I0 skeleton (docs/plans/r8-vision.md v8.0.3 section 7.1, seam S22), which
the I1 join completes and mounts from `api/app.py` (one line, inside its size guard).

- `install_r8_routes(app)`: the coaches' routes (`api/coach.py`) and the camera setup's
  (`api/camera_spots.py`, B's skeleton).
- `wire_r8(app, s, docs, keyring, now)`: `app.state.coach`, a `CoachApp` over the sealed stores
  (`coach_results`, `coach_people`, `coach_routines` under the keyring's `coach` purpose) and the
  tracking target; None when `coach_enabled` is off. Without a token key the stores answer "off"
  (never in clear). I1 adds the Faces lookup (R3's consent registry) and J's home views.
- `r8_privacy_sources(app)`: Privacy's "Health and fitness" rows (`jarvis.coach.privacy`).
- `r8_tools(app, names)`: the brain's `coach_results` (R1), for the gateway's register.

Left for I1 (I0-SEAMS.md): the app.py line; the Vitals readers (B's camera health, C's screen
time) in `OwnSources`; the posture nudge (C) on the helpers' gate; the bridge's coach state push
and the webhook handler for `CoachReport` (J); the daily sweep job (`coach_keep_days`); the voice
router's "track me / track <name> / track everyone" (`jarvis.coach.target.phrase_target`).
Nothing here makes a network call.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime

from fastapi import FastAPI

from jarvis.api.camera_spots import router as camera_router
from jarvis.api.coach import CoachApp
from jarvis.api.coach import router as coach_router
from jarvis.coach.people import PeopleStore
from jarvis.coach.privacy import coach_privacy
from jarvis.coach.store import CoachStore, RoutineStore
from jarvis.coach.target import TargetStore
from jarvis.coach.tools import results_tool
from jarvis.config import Settings
from jarvis.keyring import Keyring
from jarvis.privacy.sources import CallbackSource
from jarvis.storage.docs import Docs
from jarvis.tools.base import Tool

ROUTERS = (coach_router, camera_router)


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
        target=TargetStore(docs, prefix=prefix, now=now),
        routines=RoutineStore(docs, keyring, prefix=prefix, now=now),
    )
    app.state.coach = coach
    return coach


def r8_privacy_sources(app: FastAPI) -> tuple[CallbackSource, ...]:
    coach = getattr(app.state, "coach", None)
    return coach_privacy(coach.store, coach.people) if isinstance(coach, CoachApp) else ()


def r8_tools(app: FastAPI, names: Callable[[str], Awaitable[Mapping[str, str]]]) -> list[Tool]:
    coach = getattr(app.state, "coach", None)
    return [results_tool(coach.store, names)] if isinstance(coach, CoachApp) else []


__all__ = ["ROUTERS", "install_r8_routes", "r8_privacy_sources", "r8_tools", "wire_r8"]
