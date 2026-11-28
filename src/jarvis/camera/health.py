# src/jarvis/camera/health.py
"""R8 row 217 (docs/plans/r8-vision.md v8.0.4 section 4.5, 4.8; I0 seam S13, builder B): each
camera's health for Vitals: when it was last seen and how fast it looked. Never a picture.

    {prefix}camera_health/{uid}   {blob, updated_at}
        blob = AES-GCM(JSON HealthDoc) under the keyring's `vision` purpose, AAD
        `camera_health/{uid}/v1`

A live device posts `{camera, fps, ms}` every 5 minutes (`POST /v1/camera/health`, from the
camera's door) and once after its setup test; only his registered device cameras are taken, the
time is the server's (a device's own clock is never trusted beyond `SKEW_S`), and one camera is
written at most once every `MIN_GAP_S`. A home camera's line comes from the bridge's heartbeat
("cameras producing frames", `HomeSeen`, wired by I1), never from a device.

`HealthStore.lines(uid)` is the `jarvis.coach.ports.CameraHealth` port Vitals reads
(`jarvis.vitals.own.camera_item`: ok, amber when a switched-on camera is unseen for 24 hours,
"switched off" when its switches say so). `camera_setup_privacy` is Privacy's row for the setup
and the health figures (export, delete).
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from jarvis.camera.sealed import SealedDoc
from jarvis.camera.spots import CAMERAS_MAX, PURPOSE, CameraId, Spots, SpotsStore, looking_allowed
from jarvis.coach.ports import CameraLine
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.privacy.sources import OURS_ENC, SEC_SAFETY, CallbackSource, Look, Spec
from jarvis.storage.docs import Docs

log = get_logger(__name__)

FPS_MAX = 120.0
MS_MAX = 60_000
MIN_GAP_S = 30.0  # a camera's line is written at most this often
SKEW_S = 600.0  # a device's "last seen" may be this much older than the server's clock
PRIVACY_ID = "camera_setup"


class Seen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fps: Annotated[float, Field(ge=0, le=FPS_MAX, allow_inf_nan=False)]
    ms: Annotated[int, Field(ge=0, le=MS_MAX)] | None = None
    at: Annotated[float, Field(ge=0, allow_inf_nan=False)]


class HealthDoc(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cameras: dict[CameraId, Seen] = Field(default_factory=dict, max_length=CAMERAS_MAX)


class UnknownCamera(Exception):
    """Not one of his registered device cameras: nothing is written."""


HomeSeen = Callable[[str], Awaitable[Mapping[str, float]]]  # home camera id -> last time seen


def _rate(fps: float | None) -> float | None:
    """Vitals' words print the number as it is: one decimal under 10 a second, whole above."""
    if fps is None:
        return None
    return round(fps, 1) if fps < 10 else float(round(fps))


class HealthStore:
    """The `CameraHealth` port: reports from his devices in, one line per camera out."""

    def __init__(
        self,
        docs: Docs,
        keyring: Keyring,
        spots: SpotsStore,
        *,
        prefix: str = "jarvis_",
        home_seen: HomeSeen | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._doc: SealedDoc[HealthDoc] = SealedDoc(
            docs,
            keyring,
            collection=f"{prefix}camera_health",
            purpose=PURPOSE,
            name="camera_health",
            model=HealthDoc,
        )
        self._spots = spots
        self._home_seen = home_seen
        self._clock = clock

    async def report(self, uid: str, camera: str, *, fps: float, ms: int, at: float) -> None:
        spots = await self._spots.get(uid)
        cam = spots.camera(camera)
        if cam is None or cam.kind != "device":
            raise UnknownCamera(camera)
        now = self._clock()
        when = at if now - SKEW_S <= at <= now else now
        seen = Seen(fps=fps, ms=ms, at=when)
        known = {c.id for c in spots.cameras}

        def change(cur: HealthDoc) -> HealthDoc | None:
            old = cur.cameras.get(camera)
            if old is not None and 0 <= when - old.at < MIN_GAP_S:
                return None
            kept = {k: v for k, v in cur.cameras.items() if k in known}  # forgotten cameras go
            return HealthDoc(cameras={**kept, camera: seen})

        await self._doc.update(uid, change)

    async def lines(self, uid: str) -> list[CameraLine]:
        spots = await self._spots.get(uid)
        doc = await self._doc.load(uid)
        home = await self._home(uid) if any(c.kind == "home" for c in spots.cameras) else {}
        out: list[CameraLine] = []
        for cam in spots.cameras:
            on = looking_allowed(spots, cam.id)
            if cam.kind == "home":
                at = home.get(cam.id)
                out.append(CameraLine(cam.id, cam.label, cam.source, on, at, None))
                continue
            seen = doc.cameras.get(cam.id)
            if seen is None:
                out.append(CameraLine(cam.id, cam.label, cam.source, on, None, None))
            else:
                line = CameraLine(
                    cam.id, cam.label, cam.source, on, seen.at, _rate(seen.fps), seen.ms
                )
                out.append(line)
        return out

    async def export(self, uid: str) -> dict[str, Any]:
        doc = await self._doc.load(uid)
        return {cid: s.model_dump(mode="json") for cid, s in doc.cameras.items()}

    async def count(self, uid: str) -> int:
        return len((await self._doc.load(uid)).cameras)

    async def wipe(self, uid: str) -> None:
        await self._doc.delete(uid)

    async def _home(self, uid: str) -> dict[str, float]:
        if self._home_seen is None:
            return {}
        try:
            got = await self._home_seen(uid)
        except Exception as exc:  # noqa: BLE001 - a home line says "not seen" rather than fail
            log.warning("home camera health unreadable", extra={"error": type(exc).__name__})
            return {}
        return {str(k): float(v) for k, v in got.items() if isinstance(v, int | float)}


def _setup_export(spots: Spots, health: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "cameras": [c.model_dump(mode="json") for c in spots.cameras],
        "rooms": [r.model_dump(mode="json") for r in spots.rooms],
        "all_off": spots.all_off,
        "health": dict(health),
    }


def camera_setup_privacy(spots: SpotsStore, health: HealthStore) -> CallbackSource:
    """Privacy's row for the camera setup: his cameras' names, spots, rooms and switches, and
    each camera's last-seen time and rate. Delete forgets them (every camera then needs setting up
    again); it never touches the alarm or a camera itself."""

    async def look(uid: str) -> Look:
        s = await spots.get(uid)
        n = len(s.cameras) + len(s.rooms) + await health.count(uid)
        return Look(n, [s.rev, n], deletable=n > 0 or s.all_off)

    async def export(uid: str) -> dict[str, Any]:
        return _setup_export(await spots.get(uid), await health.export(uid))

    async def delete(uid: str) -> int:
        s = await spots.get(uid)
        n = len(s.cameras) + len(s.rooms) + await health.count(uid)
        await health.wipe(uid)
        await spots.wipe(uid)
        return n

    spec = Spec(
        PRIVACY_ID,
        SEC_SAFETY,
        "Camera setup and health",
        "Your cameras' names, spots, rooms and off switches, and when each was last seen and how "
        "fast it looked.",
        "items",
        "Until you delete them",
        OURS_ENC,
        encrypted_by_jarvis=True,
        delete="confirm",
        note="Never kept: a picture or a video. Deleting doesn't change the burglar alarm.",
    )
    return CallbackSource(spec, look, export, delete)


__all__ = [
    "MIN_GAP_S",
    "PRIVACY_ID",
    "SKEW_S",
    "HealthDoc",
    "HealthStore",
    "HomeSeen",
    "Seen",
    "UnknownCamera",
    "camera_setup_privacy",
]
