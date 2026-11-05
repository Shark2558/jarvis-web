# src/jarvis/api/camera.py
"""The Home panel's HTTP surface: alarm, cameras, feed and history (R3 B; Layer 1 -> 6).

Owner-only: `require_auth` + `current_user` (no client user id is read); cookie writes need
`X-Requested-With: JARVIS`. Errors are `{error, detail, reason?}` in plain words.

GET  /v1/home/alarm        {available, armed, mode, confirmed, pending_since, set_via,
                            dropped_disarmed, disarm_target}
POST /v1/home/arm          {mode: away|night} -> the alarm view (pending until the laptop acks)
POST /v1/home/disarm       {proof?} -> the alarm view. Console only: a bearer token gets 403
                            console_only; the passkey is checked for exactly this home and arm rev
                            (403 passkey_required / passkey_rejected / proof_required); without
                            passkeys a Google sign-in under 5 minutes old (403 reauth_required)
GET  /v1/home/cameras      {available, cameras: [{id, label, alarm_zones, package_zone, online,
                            last_event_at}], retention_days, greetings, model_note}
PUT  /v1/home/cameras      {cameras: {<id>: {label, alarm_zones, package_zone?}}, retention_days?,
                            greetings?}
GET  /v1/home/feed?day=today|yesterday   {items: [{at, words, camera, zone, who, decision, sent}]}
GET  /v1/home/history?what&from&to&camera&zone&who&limit   as the camera_history tool
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from jarvis.api.auth import fresh_sign_in_left, require_auth
from jarvis.api.identity import current_user
from jarvis.api.ratelimit import RateLimiter
from jarvis.api.settings_audit import record_change
from jarvis.camera.history import HistoryRejected
from jarvis.camera.models import (
    LABEL_MAX,
    MAX_LIMIT,
    CameraConfig,
    HistoryQuery,
)
from jarvis.camera.packages import model_note
from jarvis.camera.ports import AlarmRefused, CameraUnavailable
from jarvis.camera.service import CameraServices
from jarvis.core.guardrails import ActionRisk
from jarvis.home.ports import MAX_CAMERAS, MAX_ZONES, CameraId, HomeUnavailable, ZoneId
from jarvis.logging import get_logger
from jarvis.permissions.models import PasskeyProof

log = get_logger(__name__)

VIEW_PER_MINUTE = 60
CHANGE_PER_MINUTE = 30
NOT_AVAILABLE = "Not available on this server (no encryption key)."
NO_ZONES_WARNING = (
    "JARVIS is not protecting anything yet: no camera has an alarm zone. "
    "Choose the gate zone under Cameras."
)
router = APIRouter(prefix="/v1/home", dependencies=[Depends(require_auth)])


class ArmBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["away", "night"] = "away"


class DisarmBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proof: PasskeyProof | None = None


class CameraBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(max_length=LABEL_MAX * 4)
    alarm_zones: list[ZoneId] = Field(default_factory=list, max_length=MAX_ZONES)
    package_zone: ZoneId | None = None


class CamerasBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cameras: dict[CameraId, CameraBody] = Field(max_length=MAX_CAMERAS)
    retention_days: int | None = Field(default=None, ge=1, le=30)
    greetings: StrictBool | None = None


def _svc(request: Request) -> CameraServices | None:
    svc: CameraServices | None = getattr(request.app.state, "camera", None)
    return svc


def _need(svc: CameraServices | None) -> CameraServices:
    if svc is None:
        raise CameraUnavailable(NOT_AVAILABLE)
    return svc


def _limit(request: Request, name: str, uid: str) -> None:
    allowed, _ = request.app.state.camera_limits[name].allow(uid)
    if not allowed:
        raise AlarmRefused("rate_limited", "Too many requests; wait a moment.")


async def _alarm_view(svc: CameraServices, uid: str) -> dict[str, Any]:
    rec = await svc.alarm.record(uid)
    home = await svc.gate.homes.home_id(uid) if rec.armed else None
    zones = await svc.alarm.protecting(uid)
    return {
        "available": True,
        # what the passkey check for Disarm is bound to; no secret (an id and a counter)
        "disarm_target": f"{home}:{rec.rev}" if home else None,
        "armed": rec.armed,
        "mode": rec.mode,
        "confirmed": rec.confirmed,
        "pending_since": None if rec.confirmed else rec.pending_since,
        "set_via": rec.set_via,
        "dropped_disarmed": rec.dropped_disarmed,
        "zones_configured": zones,
        "warning": NO_ZONES_WARNING if rec.armed and not zones else None,
    }


@router.get("/alarm")
async def alarm_get(
    request: Request, svc: CameraServices | None = Depends(_svc), uid: str = Depends(current_user)
) -> dict[str, Any]:
    if svc is None:
        return {"available": False, "reason": NOT_AVAILABLE, "armed": False}
    _limit(request, "view", uid)
    return await _alarm_view(svc, uid)


@router.post("/arm")
async def arm_post(
    body: ArmBody,
    request: Request,
    svc: CameraServices | None = Depends(_svc),
    uid: str = Depends(current_user),
) -> dict[str, Any]:
    s = _need(svc)
    _limit(request, "change", uid)
    await s.alarm.arm(uid, body.mode, "console")
    await record_change(request, agent="home", tool="home_arm", args={"mode": body.mode})
    return await _alarm_view(s, uid)


@router.post("/disarm")
async def disarm_post(
    body: DisarmBody,
    request: Request,
    svc: CameraServices | None = Depends(_svc),
    uid: str = Depends(current_user),
) -> dict[str, Any]:
    s = _need(svc)
    _limit(request, "change", uid)
    fresh = fresh_sign_in_left(request, request.app.state.settings)  # None: a bearer token
    approved = await s.gate.panel_pass(uid, body.proof, fresh_left_s=fresh)
    if approved is not None:
        gw = getattr(request.app.state, "gateway", None)
        if gw is None:
            raise CameraUnavailable("The alarm can't be switched off while the audit is down.")
        try:  # audit first: a security downgrade is never unrecorded
            await gw.audit.append(
                agent="home",
                tool="home_disarm",
                risk=ActionRisk.IRREVERSIBLE,
                outcome="executed",
                args={},
                detail=f"console, {approved.how}",
            )
        except Exception as exc:  # noqa: BLE001
            log.error("AUDIT WRITE FAILED for a disarm", extra={"error": type(exc).__name__})
            raise CameraUnavailable(
                "The alarm can't be switched off while the audit is down."
            ) from None
        await s.alarm.disarm(uid, approved, via="console")
    return await _alarm_view(s, uid)


@router.get("/cameras")
async def cameras_get(
    request: Request, svc: CameraServices | None = Depends(_svc), uid: str = Depends(current_user)
) -> dict[str, Any]:
    if svc is None:
        return {"available": False, "reason": NOT_AVAILABLE, "cameras": []}
    _limit(request, "view", uid)
    st = await svc.config.get(uid)
    return {
        "available": True,
        "cameras": [
            {
                "id": cid,
                "label": c.label,
                "alarm_zones": list(c.alarm_zones),
                "package_zone": c.package_zone,
                "online": st.status.online.get(cid),
                "last_event_at": st.status.last_event.get(cid),
            }
            for cid, c in st.cameras.items()
        ],
        "retention_days": st.retention_days,
        "greetings": st.greetings,
        "model_note": model_note(st),
    }


@router.put("/cameras")
async def cameras_put(
    body: CamerasBody,
    request: Request,
    svc: CameraServices | None = Depends(_svc),
    uid: str = Depends(current_user),
) -> dict[str, Any]:
    s = _need(svc)
    _limit(request, "change", uid)
    cams = {
        cid: CameraConfig(
            label=c.label.strip() or cid.replace("_", " "),
            alarm_zones=tuple(c.alarm_zones),
            package_zone=c.package_zone,
        )
        for cid, c in body.cameras.items()
    }
    await s.config.set_cameras(
        uid, cams, retention_days=body.retention_days, greetings=body.greetings
    )
    await record_change(request, agent="home", tool="camera_settings", args={"cameras": len(cams)})
    return await cameras_get(request, svc, uid)


@router.get("/feed")
async def feed_get(
    request: Request,
    day: Annotated[str, Query(pattern="^(today|yesterday)$")] = "today",
    svc: CameraServices | None = Depends(_svc),
    uid: str = Depends(current_user),
) -> dict[str, Any]:
    if svc is None:
        return {"available": False, "reason": NOT_AVAILABLE, "items": []}
    _limit(request, "view", uid)
    return {"available": True, "items": await svc.feed.view(uid, day)}


@router.get("/history")
async def history_get(
    request: Request,
    from_: Annotated[datetime, Query(alias="from")],
    to: datetime,
    what: Annotated[str, Query(max_length=20)] = "any",
    camera: Annotated[str | None, Query(max_length=24)] = None,
    zone: Annotated[str | None, Query(max_length=24)] = None,
    who: Annotated[str | None, Query(max_length=24)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = MAX_LIMIT,
    svc: CameraServices | None = Depends(_svc),
    uid: str = Depends(current_user),
) -> Any:
    s = _need(svc)
    _limit(request, "view", uid)
    q = HistoryQuery(
        what=what,
        start=from_,
        end=to,
        camera=camera,
        zone=zone,
        who=who,
        limit=limit,
    )
    try:
        res = await s.history.search(uid, q)
    except HomeUnavailable as exc:
        return _err(503 if exc.code == "offline" else 502, "home_" + exc.code, exc.message)
    return res.model_dump(mode="json")


def _err(status: int, code: str, detail: str, reason: str | None = None) -> JSONResponse:
    body = {"error": code, "detail": detail}
    if reason:
        body["reason"] = reason
    return JSONResponse(status_code=status, content=body)


_REFUSED = {
    "console_only": (403, None),
    "reauth_required": (403, "reauth"),
    "no_pass": (403, None),
    "not_linked": (409, None),
    "changed": (409, None),
    "needs_console": (403, None),
    "rate_limited": (429, None),
}


def install_camera(app: FastAPI) -> None:
    """Mount /v1/home alarm, cameras, feed and history, their per-owner limits and error mapping.
    The services are `app.state.camera` (None: the routes say it is not available)."""
    app.state.camera_limits = {
        "view": RateLimiter(VIEW_PER_MINUTE),
        "change": RateLimiter(CHANGE_PER_MINUTE),
    }

    @app.exception_handler(AlarmRefused)
    async def _refused(_: Request, exc: AlarmRefused) -> JSONResponse:
        status, reason = _REFUSED.get(exc.code, (403, None))
        return _err(status, exc.code, exc.message, reason)

    @app.exception_handler(CameraUnavailable)
    async def _unavailable(_: Request, exc: CameraUnavailable) -> JSONResponse:
        return _err(503, "unavailable", str(exc))

    @app.exception_handler(HistoryRejected)
    async def _rejected(_: Request, exc: HistoryRejected) -> JSONResponse:
        return _err(422, "input_rejected", str(exc))

    app.include_router(router)


__all__ = ["install_camera", "router"]
