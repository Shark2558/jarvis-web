# src/jarvis/camera/spots.py
"""R8 rows 217 and 184 (docs/plans/r8-vision.md v8.0.3 section 4.5; I0 seam S12, builder B from I0
on): his cameras, their spots and rooms, and the off switches.

    {prefix}camera_spots/{uid}   sealed under the keyring's `vision` purpose (B builds the store)

A camera is `{id, kind: device|home, source: browser|phone|home, label (his words), spot, room,
on}`: the desk webcam and the workout phone are device cameras (registered from the device that
has them); a home camera (his Imou Ranger S2) comes from the bridge's camera list. A room is
`{id, label, never}`: a "never" room can't be chosen for any coach. `all_off` is "cameras off"
(D11): every camera's looking stops on every device and on the home laptop; it never disarms the
alarm and never switches Frigate. Ids are the home kit's camera ids (`jarvis.home.ports.LABEL_ID`).
`looking_allowed` is the one rule every device and the home laptop apply (when a look starts and
every 60 s while it runs).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from jarvis.coach.sources import SourceKind
from jarvis.home.ports import LABEL_ID

CAMERAS_MAX = 12
ROOMS_MAX = 12
RECHECK_S = 60  # a live device reads the switches this often (and when its camera starts)
CameraId = Annotated[str, StringConstraints(pattern=LABEL_ID)]
Words = Annotated[str, StringConstraints(min_length=1, max_length=40, pattern=r"^[^<>\x00-\x1f]+$")]
Spot = Literal["desk", "workout", "table", "room", "none"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Room(_Strict):
    id: CameraId
    label: Words
    never: bool = False


class Camera(_Strict):
    id: CameraId
    kind: Literal["device", "home"]
    source: SourceKind
    label: Words
    spot: Spot = "none"
    room: CameraId | None = None
    on: bool = True

    @model_validator(mode="after")
    def _kind_and_source(self) -> Camera:
        if (self.kind == "home") != (self.source == "home"):
            raise ValueError(
                "a home camera is looked at on the home laptop, a device camera on its device"
            )
        return self


class Spots(_Strict):
    rev: int = Field(default=0, ge=0)
    cameras: tuple[Camera, ...] = Field(default=(), max_length=CAMERAS_MAX)
    rooms: tuple[Room, ...] = Field(default=(), max_length=ROOMS_MAX)
    all_off: bool = False

    @model_validator(mode="after")
    def _known_rooms(self) -> Spots:
        rooms = {r.id for r in self.rooms}
        if len(rooms) != len(self.rooms) or len({c.id for c in self.cameras}) != len(self.cameras):
            raise ValueError("each camera and room once")
        if any(c.room is not None and c.room not in rooms for c in self.cameras):
            raise ValueError("a camera's room must be one of his rooms")
        return self


def looking_allowed(spots: Spots, camera: str) -> bool:
    """False when every camera, that camera or its room is switched off, or it isn't his."""
    if spots.all_off:
        return False
    cam = next((c for c in spots.cameras if c.id == camera), None)
    if cam is None or not cam.on:
        return False
    room = next((r for r in spots.rooms if r.id == cam.room), None)
    return not (room and room.never)


def coach_allowed(spots: Spots, camera: str) -> bool:
    """A coach may be started on it: looking allowed and not in a "never" room."""
    return looking_allowed(spots, camera)


__all__ = [
    "CAMERAS_MAX",
    "RECHECK_S",
    "ROOMS_MAX",
    "Camera",
    "Room",
    "Spots",
    "coach_allowed",
    "looking_allowed",
]
