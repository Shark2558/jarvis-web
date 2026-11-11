# src/jarvis/api/home.py
"""The home link over HTTP (R3 D3-D6; Layer 1 -> 6). `install_home(app)` mounts everything A owns.

Outside /v1 (like /telegram/webhook), each with its own door:
  POST /home/link               no session: `{code, bridge_url, bridge_version, link_secret}` ->
                                201 `{home_id, seed}` ONCE; bare 401 wrong code; 422 bad address
                                (plain words); 409 not_reachable; 10 a minute per client
  POST /home/webhook            HMAC up-key (jarvis.home.webhook), bare 401; 404 when Home is off
  POST /internal/home/watchdog  Cloud Scheduler OIDC, audience = this exact URL ->
                                `{homes, offline, held_sent, swept, jobs}`; 503 (same body)
                                when any job failed, so the Scheduler shows it. Home off: only
                                R11's helpers clock runs here (advisory, never a 503)

Owner only (`require_auth` + `current_user`, errors `{error, detail, reason?}`):
  GET    /v1/home               {available, reason?, linked, state, host, last_seen_at, parts,
                                 bridge_version, kit_outdated, devices_available}
  POST   /v1/home/link-code     {code, expires_in_s}
  DELETE /v1/home/link?confirm=1  unlink (audited); while armed it is a disarm too: body
                                {proof?} and exactly the Disarm button's rules (403
                                console_only / reauth_required / passkey_required)
  GET    /v1/home/kit           the zip, `X-Kit-Sha256`, `Cache-Control: no-store`
  GET    /v1/home/kit/info      {sha256, size, version}
  GET    /v1/home/devices[?catalogue=1]   the exposed list, or what he could expose
  PUT    /v1/home/devices       {entities:[{entity_id, label?, class}]} (<= 50)

Without the token key Home is OFF: `/home/*` answer 404 and /v1/home says why.
"""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from jarvis.api.auth import fresh_sign_in_left, require_auth
from jarvis.api.identity import current_user
from jarvis.api.ratelimit import RateLimiter, client_key
from jarvis.api.scheduler_auth import WATCHDOG_PATH, require_scheduler
from jarvis.api.settings_audit import record_change
from jarvis.camera.guard import ArmedUnlinkGuard
from jarvis.home import kit
from jarvis.home.devices import DeviceRejected, DeviceService
from jarvis.home.link import LinkRefused, LinkService
from jarvis.home.ports import HomeUnavailable
from jarvis.home.store import HomeStore, HomeStoreUnavailable
from jarvis.home.watchdog import WATCHDOG_BUDGET_S, Watchdog
from jarvis.home.webhook import HomeWebhook
from jarvis.logging import get_logger
from jarvis.permissions.models import PasskeyProof
from jarvis.ticks import run_jobs

log = get_logger(__name__)

NOT_AVAILABLE = "Not available on this server (no encryption key)."
LINKS_PER_MINUTE = 10
CHANGES_PER_MINUTE = 30
router = APIRouter(prefix="/v1/home", dependencies=[Depends(require_auth)])
public = APIRouter()
internal = APIRouter(prefix="/internal/home")


class LinkBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(max_length=40)
    bridge_url: str = Field(max_length=300)
    bridge_version: str = Field(max_length=20)
    link_secret: str = Field(max_length=64)


class UnlinkBody(BaseModel):
    """Only needed while armed: the Disarm button's passkey check (home_disarm, this home and
    arm rev)."""

    model_config = ConfigDict(extra="forbid")
    proof: PasskeyProof | None = None


class DeviceRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: str = Field(max_length=100)
    label: str | None = Field(default=None, max_length=160)
    class_: str = Field(alias="class", max_length=20)


class DevicesBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entities: list[DeviceRow] = Field(max_length=50)


def _err(status: int, error: str, detail: str, **extra: Any) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": error, "detail": detail, **extra},
        headers={"Cache-Control": "no-store"},
    )


def _svc(request: Request, name: str) -> Any:
    return getattr(request.app.state, name, None)


# ---- the three doors outside /v1 ----------------------------------------------------------------


@public.post("/home/link", response_model=None)
async def home_link(request: Request, body: LinkBody) -> Response:
    link: LinkService | None = _svc(request, "home_link")
    if link is None:
        return Response(status_code=404)
    limiter: RateLimiter = request.app.state.home_link_limit
    if not limiter.allow(client_key(request))[0]:
        return Response(status_code=429, headers={"Retry-After": "60"})
    try:
        linked = await link.complete(
            body.code,
            body.bridge_url,
            body.bridge_version,
            body.link_secret,
            client=client_key(request),
        )
    except LinkRefused as exc:
        if exc.code == "bad_code":
            return Response(status_code=401, headers={"Cache-Control": "no-store"})
        status = 409 if exc.code == "not_reachable" else 422
        return _err(status, exc.code, exc.reason)
    except HomeStoreUnavailable as exc:
        return _err(503, "unavailable", str(exc))
    seed = base64.urlsafe_b64encode(linked.seed).decode("ascii").rstrip("=")
    return JSONResponse(
        status_code=201,
        content={"home_id": linked.home_id, "seed": seed},
        headers={"Cache-Control": "no-store"},
    )


@public.post("/home/webhook", response_model=None)
async def home_webhook(request: Request) -> Response:
    hook: HomeWebhook | None = _svc(request, "home_webhook")
    if hook is None:
        return Response(status_code=404)
    return await hook.receive(request)


@internal.post("/watchdog", dependencies=[Depends(require_scheduler)], response_model=None)
async def home_watchdog(request: Request) -> dict[str, Any] | JSONResponse:
    dog: Watchdog | None = _svc(request, "home_watchdog")
    if dog is None:  # R11 D3: with Home off the same Scheduler job is the helpers' 5-minute clock
        return await _helpers_clock_only(request)
    out = await dog.run()
    jobs = out.get("jobs")
    if isinstance(jobs, dict) and "failed" in jobs.values():
        return JSONResponse(status_code=503, content=out)  # M9: the Scheduler shows the failure
    return out


async def _helpers_clock_only(request: Request) -> dict[str, Any]:
    """R11 D3: Home is off, so no laptop check runs; the helpers' clock (if any) still does, and
    is advisory: a job it could not finish is "degraded", never a 503 (the Scheduler would retry
    a 5-minute job for nothing)."""
    out: dict[str, Any] = {"homes": 0, "offline": 0, "held_sent": 0, "swept": 0, "jobs": {}}
    clock = getattr(request.app.state, "helpers_clock", None)
    if clock is None:
        return out
    got = await run_jobs((clock,), (), total_budget_s=WATCHDOG_BUDGET_S)
    out["jobs"] = {name: "degraded" if res == "failed" else res for name, res in got.items()}
    return out


# ---- the owner's side ---------------------------------------------------------------------------


def _host_of(url: str) -> str:
    return urlsplit(url).hostname or ""


@router.get("")
async def home_get(request: Request, uid: str = Depends(current_user)) -> dict[str, Any]:
    store: HomeStore | None = _svc(request, "home_store")
    if store is None:
        return {"available": False, "reason": NOT_AVAILABLE, "linked": False}
    settings = request.app.state.settings
    rec = await store.load(uid)
    status = await store.status(uid)
    if rec is None or status is None:
        return {
            "available": True,
            "linked": False,
            "state": "not_linked",
            "devices_available": False,
        }
    now = store.now()
    seen = status.last_seen_at
    state = status.state
    if seen is not None and now - seen > settings.home_offline_after_s:
        state = "offline"
    return {
        "available": True,
        "linked": True,
        "state": state,
        "host": _host_of(rec.bridge_url),
        "last_seen_at": seen,
        "parts": status.parts,
        "bridge_version": status.bridge_version,
        "kit_outdated": kit.outdated(status.bridge_version),
        "devices_available": bool(status.parts.get("ha")),
        "dropped_disarmed": await _dropped(request, uid, status.dropped_disarmed),
    }


async def _dropped(request: Request, uid: str, stored: int) -> int:
    """I1: B counts detections dropped while disarmed in its arm record (D8); A's field is the
    fallback when the camera isn't wired or can't be read."""
    camera = _svc(request, "camera")
    if camera is None:
        return stored
    try:
        return max(stored, int((await camera.alarm.record(uid)).dropped_disarmed))
    except Exception as exc:  # noqa: BLE001 - the status line still shows
        log.warning("dropped count unreadable", extra={"error": type(exc).__name__})
        return stored


@router.post("/link-code")
async def home_link_code(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    link: LinkService | None = _svc(request, "home_link")
    if link is None:
        return _err(503, "unavailable", NOT_AVAILABLE)
    if not request.app.state.home_change_limit.allow(uid)[0]:
        return _err(429, "rate_limited", "Too many tries; wait a moment.")
    made = await link.code(uid)
    return JSONResponse(
        {"code": made.code, "expires_in_s": made.expires_in_s},
        headers={"Cache-Control": "no-store"},
    )


@router.delete("/link")
async def home_unlink(
    request: Request,
    body: UnlinkBody | None = None,
    confirm: str | None = Query(default=None, max_length=5),
    uid: str = Depends(current_user),
) -> JSONResponse:
    store: HomeStore | None = _svc(request, "home_store")
    if store is None:
        return _err(503, "unavailable", NOT_AVAILABLE)
    if confirm != "1":
        return _err(422, "confirm_required", "Confirm that you want to unlink your home laptop.")
    guard: ArmedUnlinkGuard | None = _svc(request, "home_unlink_guard")
    if guard is not None:  # S4: armed -> the Disarm button's proof, audited as a disarm, first
        await guard.check(
            uid,
            body.proof if body is not None else None,
            fresh_left_s=fresh_sign_in_left(request, request.app.state.settings),
            where="unlink",
            from_panel=True,
        )
    had = await store.unlink(uid)
    await record_change(
        request, agent="owner", tool="home_unlink", args={"linked": had}, detail="unlinked"
    )
    return JSONResponse({"unlinked": had})


@router.get("/kit", response_model=None)
async def home_kit(request: Request, uid: str = Depends(current_user)) -> Response:
    base = request.app.state.settings.public_base_url
    try:
        data = kit.build(str(base or ""), kit_root(request))
    except kit.KitError as exc:
        return _err(503, "kit_unavailable", str(exc))
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="JARVIS-Home-kit.zip"',
            "X-Kit-Sha256": kit.sha256(data),
            "Cache-Control": "no-store",
        },
    )


@router.get("/kit/info")
async def home_kit_info(request: Request, uid: str = Depends(current_user)) -> Any:
    base = request.app.state.settings.public_base_url
    try:
        data = kit.build(str(base or ""), kit_root(request))
    except kit.KitError as exc:
        return _err(503, "kit_unavailable", str(exc))
    return {"sha256": kit.sha256(data), "size": len(data), "version": kit.KIT_VERSION}


def kit_root(request: Request) -> Any:
    return getattr(request.app.state, "home_kit_root", None)


@router.get("/devices")
async def home_devices_get(
    request: Request,
    catalogue: str | None = Query(default=None, max_length=2),
    uid: str = Depends(current_user),
) -> Any:
    devices: DeviceService | None = _svc(request, "home_devices")
    if devices is None:
        return _err(503, "unavailable", NOT_AVAILABLE)
    if catalogue == "1":
        return {"devices": await devices.catalogue(uid)}
    rec = await devices.exposed(uid)
    return {
        "rev": rec.rev,
        "entities": [
            {"entity_id": e.entity_id, "label": e.label, "name": e.name, "class": e.tier}
            for e in rec.entries
        ],
    }


@router.put("/devices")
async def home_devices_put(
    body: DevicesBody, request: Request, uid: str = Depends(current_user)
) -> Any:
    devices: DeviceService | None = _svc(request, "home_devices")
    if devices is None:
        return _err(503, "unavailable", NOT_AVAILABLE)
    if not request.app.state.home_change_limit.allow(uid)[0]:
        return _err(429, "rate_limited", "Too many changes; wait a moment.")
    wanted = [
        {"entity_id": r.entity_id, "label": r.label, "class": r.class_} for r in body.entities
    ]
    rec = await devices.expose(uid, wanted)
    await record_change(
        request,
        agent="owner",
        tool="home_devices",
        args={"count": len(rec.entries)},
        detail="changed",
    )
    return {"rev": rec.rev, "count": len(rec.entries)}


def install_home(app: FastAPI) -> None:
    """Mount the routes, the limits and the error mapping. The services are `app.state.home_*`
    (None: Home is off and the doors answer 404 / say why)."""
    app.state.home_link_limit = RateLimiter(LINKS_PER_MINUTE)
    app.state.home_change_limit = RateLimiter(CHANGES_PER_MINUTE)

    @app.exception_handler(HomeStoreUnavailable)
    async def _unavailable(_: Request, exc: HomeStoreUnavailable) -> JSONResponse:
        return _err(503, "unavailable", str(exc))

    @app.exception_handler(HomeUnavailable)
    async def _unreachable(_: Request, exc: HomeUnavailable) -> JSONResponse:
        error = "laptop_off" if exc.code == "offline" else exc.code
        return _err(409, error, exc.message)

    @app.exception_handler(DeviceRejected)
    async def _rejected(_: Request, exc: DeviceRejected) -> JSONResponse:
        return _err(422, exc.code, exc.message)

    app.include_router(public)
    app.include_router(internal)
    app.include_router(router)


__all__ = ["WATCHDOG_PATH", "install_home"]
