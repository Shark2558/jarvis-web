# src/jarvis/api/camera_spots.py
"""R8 rows 217, 184 and 377 (docs/plans/r8-vision.md v8.0.4 sections 4.5, 4.6; I0 seam S12,
builder B): camera setup, the off switches, camera health and the no-cloud camera check.
Owner-only (`require_auth` + `current_user`), `no-store`, JSON object bodies of at most 16 KB.
Errors are `{error, detail}` in plain words, never library text.

    GET  /v1/camera/spots    his cameras, rooms and switches, with `allowed`, `why` and `coach`
                             per camera (`jarvis.camera.spots.view_of`), the home kit's cameras
                             not set up yet, each camera's `health` and the server's `now`
    PUT  /v1/camera/spots    the whole set with the `rev` it was read at (a stale one: 409)
    POST /v1/camera/off      "cameras off" (D11): every camera's looking stops; the answer says
                             whether the burglar alarm is still armed (it is never disarmed here)
    POST /v1/camera/health   {camera, fps, ms, last_seen?} from a live device (its door, every 5
                             minutes) or its setup test
    POST /v1/camera/check    {action: start|status, ip, stage: first|offline, onvif_port,
                             rtsp_port}: the home laptop's no-cloud check
                             (`/bridge/v1/camera-check`) for a private-range address; the
                             answer is pass or fail and the missing piece, never a stream
                             address or a password

`app.state.camera_setup` is a `CameraSetupApp` (`build_camera_setup`, wired by I1 in
`api/r8_wiring.py`); set to None (no token key) every route answers 404 `cameras_off`, and
before I1 sets it at all, 501 `not_built` (I0's skeleton answer).
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from jarvis.api.auth import require_auth
from jarvis.api.body import BodyTooLarge, read_capped
from jarvis.api.identity import current_user
from jarvis.camera.health import HealthStore, HomeSeen, UnknownCamera
from jarvis.camera.ports import CameraUnavailable
from jarvis.camera.spots import (
    HomeCameras,
    OnChange,
    Spots,
    SpotsStore,
    StaleSpots,
    view_of,
)
from jarvis.home.ports import (
    CAMERA_CHECK_ROUTE,
    LABEL_ID,
    ArmReader,
    HomeCaller,
    HomeOffline,
    HomeUnavailable,
)
from jarvis.homebridge.camcheck import PRIVATE_ONLY, private_ip
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.storage.docs import Docs

log = get_logger(__name__)

BODY_MAX = 16 * 1024
NO_STORE = {"Cache-Control": "no-store"}
OFF = {"error": "cameras_off", "detail": "Camera setup needs JARVIS's keys on this server."}
NOT_BUILT = {"error": "not_built", "detail": "Camera setup isn't wired on this server yet."}
UNAVAILABLE = "Your camera setup couldn't be read just now, Sir. Try again in a minute."
STALE = "The cameras were changed on another device. Here they are as they are now."
BAD = "That request isn't one JARVIS takes."
NOT_HIS = "That camera isn't set up in Camera, Cameras."
NO_KIT = "The camera check runs on your home laptop, which isn't linked yet: link it in Home."
KIT_OFF = "Your home laptop didn't answer, so the camera can't be checked right now."
router = APIRouter(prefix="/v1/camera", dependencies=[Depends(require_auth)])


@dataclass
class CameraSetupApp:
    spots: SpotsStore
    health: HealthStore
    caller: HomeCaller | None = None  # the bridge (camera check)
    arm: ArmReader | None = None  # the burglar alarm's state, read only (D11's reply)


def build_camera_setup(
    docs: Docs,
    keyring: Keyring | None,
    *,
    prefix: str = "jarvis_",
    caller: HomeCaller | None = None,
    arm: ArmReader | None = None,
    home_cameras: HomeCameras | None = None,
    home_seen: HomeSeen | None = None,
    on_change: OnChange | None = None,
    clock: Callable[[], float] = time.time,
) -> CameraSetupApp | None:
    """I1's one call (api/r8_wiring.py): None without a token key (never kept in the clear)."""
    if keyring is None:
        return None
    spots = SpotsStore(docs, keyring, prefix=prefix, on_change=on_change,
                       home_cameras=home_cameras, clock=clock)  # fmt: skip
    health = HealthStore(docs, keyring, spots, prefix=prefix, home_seen=home_seen, clock=clock)
    return CameraSetupApp(spots=spots, health=health, caller=caller, arm=arm)


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OffIn(_In):
    by: Literal["voice", "button"] = "button"


class HealthIn(_In):
    camera: Annotated[str, StringConstraints(pattern=LABEL_ID)]
    fps: Annotated[float, Field(ge=0, le=120, allow_inf_nan=False)]
    ms: Annotated[int, Field(ge=0, le=60_000)] = 0
    last_seen: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None


class CheckIn(_In):
    action: Literal["start", "status"] = "start"
    ip: Annotated[str, StringConstraints(min_length=7, max_length=15)]
    stage: Literal["first", "offline"] = "first"
    onvif_port: Annotated[int, Field(ge=1, le=65535)] = 80
    rtsp_port: Annotated[int, Field(ge=1, le=65535)] = 554


CheckId = Literal["onvif", "profiles", "rtsp_main", "rtsp_sub", "h264", "offline", "login"]


class CheckLine(_In):
    id: CheckId
    ok: bool | None
    words: Annotated[str, StringConstraints(max_length=200)]


class CheckView(_In):
    """What the home laptop may tell the cloud about a check: nothing else passes."""

    ip: Annotated[str, StringConstraints(max_length=15)]
    stage: Literal["first", "offline"]
    state: Literal["none", "running", "done"]
    verdict: Literal["", "pass", "half", "fail"]
    checks: tuple[CheckLine, ...] = Field(default=(), max_length=8)
    missing: Annotated[str, StringConstraints(max_length=300)] = ""
    rounds: Annotated[int, Field(ge=0, le=20)] = 0
    rounds_done: Annotated[int, Field(ge=0, le=20)] = 0


def _answer(status: int, body: dict[str, Any]) -> JSONResponse:
    return JSONResponse(status_code=status, content=body, headers=NO_STORE)


def _app(request: Request) -> CameraSetupApp | None:
    found = getattr(request.app.state, "camera_setup", None)
    return found if isinstance(found, CameraSetupApp) else None


def _wired(request: Request) -> bool:
    """I1 sets `app.state.camera_setup` (None without a token key); before that: 501."""
    return hasattr(request.app.state, "camera_setup")


async def _body(request: Request) -> dict[str, Any]:
    raw = await read_capped(request, BODY_MAX, too_large=lambda: BodyTooLarge(BODY_MAX))
    data = json.loads(raw or b"null")
    if not isinstance(data, dict):
        raise ValueError("a JSON object")
    return data


Work = Callable[[CameraSetupApp], Awaitable[JSONResponse]]


async def _do(request: Request, uid: str, work: Work) -> JSONResponse:
    app = _app(request)
    if app is None:
        return _answer(404, OFF) if _wired(request) else _answer(501, NOT_BUILT)
    try:
        return await work(app)
    except StaleSpots:
        view = await app.spots.view(uid)
        return _answer(409, {"error": "stale", "detail": STALE, "spots": dict(view)})
    except UnknownCamera:
        return _answer(404, {"error": "not_his", "detail": NOT_HIS})
    except CameraUnavailable:
        return _answer(503, {"error": "unavailable", "detail": UNAVAILABLE})
    except BodyTooLarge:
        raise
    except (ValueError, ValidationError):
        return _answer(422, {"error": "bad_request", "detail": BAD})
    except Exception as exc:  # noqa: BLE001 - plain words, the class in the log
        log.warning("camera setup route failed", extra={"error": type(exc).__name__})
        return _answer(503, {"error": "unavailable", "detail": UNAVAILABLE})


@router.get("/spots", response_model=None)
async def camera_spots(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    async def work(a: CameraSetupApp) -> JSONResponse:
        view = dict(await a.spots.view(uid))
        view["health"] = {
            line.camera: {"last_seen": line.last_seen, "fps": line.fps, "ms": line.ms}
            for line in await a.health.lines(uid)
        }
        view["now"] = round(time.time(), 1)
        return _answer(200, view)

    return await _do(request, uid, work)


@router.put("/spots", response_model=None)
async def camera_spots_put(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    async def work(a: CameraSetupApp) -> JSONResponse:
        data = await _body(request)
        base = data.get("rev")
        if not isinstance(base, int) or isinstance(base, bool) or base < 0:
            raise ValueError("rev")
        new = Spots.model_validate(data)
        saved = await a.spots.put(uid, new, base_rev=base)
        return _answer(200, view_of(saved))

    return await _do(request, uid, work)


async def _armed(arm: ArmReader | None, uid: str) -> bool | None:
    if arm is None:
        return None
    try:
        return bool((await arm.view(uid)).armed)
    except Exception as exc:  # noqa: BLE001 - the reply leaves the alarm out rather than guess
        log.warning("alarm state unreadable for cameras off", extra={"error": type(exc).__name__})
        return None


@router.post("/off", response_model=None)
async def camera_off(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    async def work(a: CameraSetupApp) -> JSONResponse:
        body = OffIn.model_validate(await _body(request))
        await a.spots.all_off(uid, by=body.by)
        return _answer(200, {"all_off": True, "alarm_armed": await _armed(a.arm, uid)})

    return await _do(request, uid, work)


@router.post("/health", response_model=None)
async def camera_health(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    async def work(a: CameraSetupApp) -> JSONResponse:
        body = HealthIn.model_validate(await _body(request))
        at = body.last_seen if body.last_seen is not None else time.time()
        await a.health.report(uid, body.camera, fps=body.fps, ms=body.ms, at=at)
        return _answer(200, {"ok": True})

    return await _do(request, uid, work)


@router.post("/check", response_model=None)
async def camera_check(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    async def work(a: CameraSetupApp) -> JSONResponse:
        body = CheckIn.model_validate(await _body(request))
        ip = private_ip(body.ip)
        if ip is None:
            return _answer(422, {"error": "not_private", "detail": PRIVATE_ONLY})
        if a.caller is None:
            return _answer(409, {"error": "not_linked", "detail": NO_KIT})
        path = CAMERA_CHECK_ROUTE[1]
        try:
            got = await a.caller.call(
                uid, "POST", path, body.model_copy(update={"ip": ip}).model_dump()
            )
        except HomeOffline:
            return _answer(503, {"error": "home_offline", "detail": KIT_OFF})
        except HomeUnavailable as exc:
            words = NO_KIT if exc.code == "not_linked" else exc.message
            return _answer(409, {"error": exc.code, "detail": words})
        view = CheckView.model_validate(got)  # anything more (an address, a password) is refused
        if view.ip != ip:
            raise ValueError("another address")
        return _answer(200, view.model_dump(mode="json"))

    return await _do(request, uid, work)


__all__ = [
    "PRIVATE_ONLY",
    "CameraSetupApp",
    "CheckIn",
    "CheckView",
    "build_camera_setup",
    "private_ip",
    "router",
]
