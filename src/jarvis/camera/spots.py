# src/jarvis/camera/spots.py
"""R8 rows 217 and 184 (docs/plans/r8-vision.md v8.0.4 section 4.5; I0 seam S12, builder B): his
cameras, their spots and rooms, and the off switches.

    {prefix}camera_spots/{uid}   {blob, updated_at}
        blob = AES-GCM(JSON Spots) under the keyring's `vision` purpose, AAD `camera_spots/{uid}/v1`

A camera is `{id, kind: device|home, source: browser|phone|home, label (his words), spot, room,
on}`: the desk webcam and the workout phone are device cameras (registered from the device that
has them); a home camera (his Imou Ranger S2, or any RTSP/ONVIF camera that passed the no-cloud
check) carries the home kit's camera id. A room is `{id, label, on, never}`: a room switched off
stops every camera in it until a tap switches it back on; a "never" room is a standing rule: no
camera in it may look and no coach can be chosen there (row 184). `all_off` is "cameras off"
(D11, ADR-54): every camera's looking stops, on every device and on the home laptop; it never
disarms the alarm and never switches Frigate (the bridge only hears it in the coach part of the
state push: `home_uses`). Ids are the home kit's camera id shape (`jarvis.home.ports.LABEL_ID`).
`looking_allowed` is the one rule every device and the home laptop apply (when a look starts and
every `RECHECK_S` while it runs); `why_off` says why in plain words.

`SpotsStore` is the `jarvis.coach.ports.CameraSpots` port: a sealed document per owner, changed
whole with its `rev` (a stale change is refused, never merged) or by "cameras off". Each saved
change calls `on_change(uid, spots)` (I1: the coach part of the bridge's state push), best effort.
A document that can't be opened is `CameraUnavailable` and is never overwritten.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from jarvis.camera.sealed import SealedDoc
from jarvis.coach.sources import SourceKind
from jarvis.home.ports import LABEL_ID
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.storage.docs import Docs

log = get_logger(__name__)

CAMERAS_MAX = 12
ROOMS_MAX = 12
RECHECK_S = 60  # a live device reads the switches this often (and when its camera starts)
PURPOSE = "vision"
CameraId = Annotated[str, StringConstraints(pattern=LABEL_ID)]
Words = Annotated[str, StringConstraints(min_length=1, max_length=40, pattern=r"^[^<>\x00-\x1f]+$")]
Spot = Literal["desk", "workout", "table", "room", "none"]
COACH_SPOTS: frozenset[str] = frozenset({"desk", "workout", "table"})
OffBy = Literal["voice", "button", "tool"]

ALL_OFF = "Every camera is switched off. Tap Allow in Camera, Cameras, to switch them on."
CAMERA_OFF = "{camera} is switched off. Tap Allow in Camera, Cameras, to switch it on."
ROOM_OFF = "{room} is switched off, so {camera} is too. Tap Allow in Camera, Cameras."
ROOM_NEVER = "{room} is marked never for cameras, so {camera} doesn't look there."
NOT_HIS = "That camera isn't set up in Camera, Cameras."


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Room(_Strict):
    id: CameraId
    label: Words
    on: bool = True  # the room's switch: off stops every camera in it (row 217)
    never: bool = False  # never a look and never a coach here (row 184)


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

    def camera(self, camera: str) -> Camera | None:
        return next((c for c in self.cameras if c.id == camera), None)

    def room(self, room: str | None) -> Room | None:
        return next((r for r in self.rooms if r.id == room), None)


def looking_allowed(spots: Spots, camera: str) -> bool:
    """False when every camera, that camera or its room is switched off, its room is "never", or
    it isn't his."""
    return why_off(spots, camera) == ""


def why_off(spots: Spots, camera: str) -> str:
    """Plain words for why that camera may not look now; "" when it may."""
    if spots.all_off:
        return ALL_OFF
    cam = spots.camera(camera)
    if cam is None:
        return NOT_HIS
    if not cam.on:
        return CAMERA_OFF.format(camera=cam.label)
    room = spots.room(cam.room)
    if room is not None and room.never:
        return ROOM_NEVER.format(room=room.label, camera=cam.label)
    if room is not None and not room.on:
        return ROOM_OFF.format(room=room.label, camera=cam.label)
    return ""


def coach_allowed(spots: Spots, camera: str) -> bool:
    """A coach may be started on it: looking allowed (so never in a "never" room)."""
    return looking_allowed(spots, camera)


def home_uses(spots: Spots, wanted: Mapping[str, Sequence[str]]) -> dict[str, tuple[str, ...]]:
    """The coach part of the bridge's state (`CoachState.uses`): only his home cameras that may
    look now keep their use cases; "cameras off" leaves none. The alarm is not in this."""
    out: dict[str, tuple[str, ...]] = {}
    for cid, uses in wanted.items():
        cam = spots.camera(cid)
        if cam is not None and cam.kind == "home" and coach_allowed(spots, cid) and uses:
            out[cid] = tuple(uses)
    return out


class StaleSpots(LookupError):
    """Another device changed the cameras since this one read them (`rev` moved on). A
    LookupError, so the sealed document passes it on unchanged (it is not a storage failure)."""


OnChange = Callable[[str, Spots], Awaitable[None]]
HomeCameras = Callable[[str], Awaitable[Mapping[str, str]]]  # the home kit's ids -> his labels


class SpotsStore:
    """The `CameraSpots` port over one sealed document per owner."""

    def __init__(
        self,
        docs: Docs,
        keyring: Keyring,
        *,
        prefix: str = "jarvis_",
        on_change: OnChange | None = None,
        home_cameras: HomeCameras | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._doc: SealedDoc[Spots] = SealedDoc(
            docs,
            keyring,
            collection=f"{prefix}camera_spots",
            purpose=PURPOSE,
            name="camera_spots",
            model=Spots,
        )
        self._on_change = on_change
        self._home_cameras = home_cameras
        self._clock = clock

    async def get(self, uid: str) -> Spots:
        return await self._doc.load(uid)

    async def view(self, uid: str) -> Mapping[str, Any]:
        spots = await self.get(uid)
        return view_of(spots, await self._home_list(uid, spots))

    async def looking_allowed(self, uid: str, camera: str) -> bool:
        return looking_allowed(await self.get(uid), camera)

    async def put(self, uid: str, new: Spots, *, base_rev: int) -> Spots:
        """The whole set, as one device saw it at `base_rev`: saved as `base_rev + 1`."""

        def change(cur: Spots) -> Spots | None:
            if cur.rev != base_rev:
                raise StaleSpots
            fresh = new.model_copy(update={"rev": cur.rev + 1})
            same = fresh.model_copy(update={"rev": cur.rev}) == cur
            return None if same else fresh

        saved = await self._doc.update(uid, change)
        if saved.rev != base_rev:  # unchanged: nothing to tell the bridge
            await self._told(uid, saved)
        return saved

    async def all_off(self, uid: str, *, by: str) -> None:
        """'Cameras off' (D11): every camera's looking stops; the alarm is never touched."""
        if by not in ("voice", "button", "tool"):
            raise ValueError("by")

        turned: list[bool] = []

        def change(cur: Spots) -> Spots | None:
            turned[:] = [not cur.all_off]
            return (
                None
                if cur.all_off
                else cur.model_copy(update={"all_off": True, "rev": cur.rev + 1})
            )

        saved = await self._doc.update(uid, change)
        log.info("cameras off", extra={"by": by})
        if turned == [True]:
            await self._told(uid, saved)

    async def wipe(self, uid: str) -> None:
        await self._doc.delete(uid)

    async def _told(self, uid: str, spots: Spots) -> None:
        if self._on_change is None:
            return
        try:
            await self._on_change(uid, spots)
        except Exception as exc:  # noqa: BLE001 - the change is saved; the push catches up later
            log.warning("camera switches not pushed", extra={"error": type(exc).__name__})

    async def _home_list(self, uid: str, spots: Spots) -> list[dict[str, str]]:
        if self._home_cameras is None:
            return []
        try:
            kit = await self._home_cameras(uid)
        except Exception as exc:  # noqa: BLE001 - the list is a convenience; setup still works
            log.warning("home camera list unreadable", extra={"error": type(exc).__name__})
            return []
        mine = {c.id for c in spots.cameras}
        return [
            {"id": cid, "label": str(label)[:40]} for cid, label in kit.items() if cid not in mine
        ]


def view_of(spots: Spots, home: Sequence[Mapping[str, str]] = ()) -> dict[str, Any]:
    """What the panes and the devices read: the set, and for each camera whether it may look now,
    why not (plain words) and whether a coach may be chosen on it."""
    return {
        **spots.model_dump(mode="json"),
        "allowed": {c.id: looking_allowed(spots, c.id) for c in spots.cameras},
        "why": {c.id: w for c in spots.cameras if (w := why_off(spots, c.id))},
        "coach": {
            c.id: coach_allowed(spots, c.id) and c.spot in COACH_SPOTS for c in spots.cameras
        },
        "home": [dict(h) for h in home],
        "recheck_s": RECHECK_S,
    }


__all__ = [
    "ALL_OFF",
    "CAMERAS_MAX",
    "COACH_SPOTS",
    "PURPOSE",
    "RECHECK_S",
    "ROOMS_MAX",
    "Camera",
    "HomeCameras",
    "OffBy",
    "OnChange",
    "Room",
    "Spots",
    "SpotsStore",
    "StaleSpots",
    "coach_allowed",
    "home_uses",
    "looking_allowed",
    "view_of",
    "why_off",
]
