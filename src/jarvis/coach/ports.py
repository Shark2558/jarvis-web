# src/jarvis/coach/ports.py
"""R8 I0 seam S11 (docs/plans/r8-vision.md v8.0.3 section 7.1): the ports the builders implement
and I1 wires (`api/r8_wiring.py`). Each is a Protocol; nothing here does I/O.

| Port            | Built by | Over                                                              |
|-----------------|----------|-------------------------------------------------------------------|
| `CameraSpots`   | B        | `jarvis.camera.spots` (cameras, spots, rooms, the off switches)   |
| `CameraHealth`  | B        | `{prefix}camera_health/{uid}` (`POST /v1/camera/health`)          |
| `WaterLog`      | D        | `helpers.nudges.hydrate.log_water`, with Undo                     |
| `ScreenTime`    | C        | the bridge's `GET /bridge/v1/screentime` (ActivityWatch)          |
| `PostureNudge`  | C        | `helpers.nudges.posture` (kind `nudge_posture`, its caps)         |
| `HomeVision`    | J        | the home vision plugin's reports and the coach part of the state  |
| `PeopleLookup`  | I1       | R3's consent registry (`jarvis.faces`): an enrolled name -> fp_   |
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from jarvis.coach.target import PeopleLookup, TrackTarget


@dataclass(frozen=True)
class CameraLine:
    """One camera's line for Vitals and the panes (B): its health, never a picture."""

    camera: str  # the camera's id (`jarvis.camera.spots.CAMERA_ID`)
    label: str  # his words ("Desk camera")
    source: str  # browser | phone | home
    on: bool
    last_seen: float | None  # unix seconds of its last frame used, None: never
    fps: float | None  # frames a second at its last report
    ms: int | None = None  # one frame's look, milliseconds


class CameraSpots(Protocol):
    async def view(self, uid: str) -> Mapping[str, Any]: ...

    async def looking_allowed(self, uid: str, camera: str) -> bool:
        """False when that camera, its room or every camera is switched off."""
        ...

    async def all_off(self, uid: str, *, by: str) -> None:
        """'Cameras off' (D11): every camera's looking stops; the alarm is never touched."""
        ...


class CameraHealth(Protocol):
    async def report(self, uid: str, camera: str, *, fps: float, ms: int, at: float) -> None: ...

    async def lines(self, uid: str) -> Sequence[CameraLine]: ...


class WaterLog(Protocol):
    async def add_glass(self, uid: str) -> str:
        """Logs one glass in the existing water log; returns the Undo id."""
        ...

    async def undo(self, uid: str, undo_id: str) -> bool: ...


@dataclass(frozen=True)
class ScreenTimeDay:
    day: str  # yyyy-mm-dd in his zone
    active_minutes: float
    programs: Mapping[str, float]  # program name -> minutes; never a window title


class ScreenTime(Protocol):
    async def day(self, uid: str, day: str) -> ScreenTimeDay | None:
        """None: ActivityWatch is not installed, the kit is not linked, or it didn't answer."""
        ...

    async def state(self, uid: str) -> str:
        """'not_installed' | 'ok' | 'unreachable' (Vitals' screen-time line)."""
        ...


class PostureNudge(Protocol):
    async def slouched(self, uid: str, *, held_s: float, at: float) -> bool:
        """A slouch held long enough: sends one fixed sentence inside the caps; True if sent."""
        ...


class HomeVision(Protocol):
    async def push(self, uid: str, *, uses: Mapping[str, Sequence[str]], target: TrackTarget,
                   all_off: bool) -> None:  # fmt: skip
        """The coach part of the bridge's state: which use cases run on which home camera."""
        ...

    def live(self, uid: str, use: str) -> Sequence[Mapping[str, Any]]:
        """The newest view of each body the home laptop reported for a use case (memory only)."""
        ...


__all__ = [
    "CameraHealth",
    "CameraLine",
    "CameraSpots",
    "HomeVision",
    "PeopleLookup",
    "PostureNudge",
    "ScreenTime",
    "ScreenTimeDay",
    "WaterLog",
]
