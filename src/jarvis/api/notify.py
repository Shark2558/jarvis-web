# src/jarvis/api/notify.py
"""Alert settings and browser notifications over HTTP (R3 D10, D11; Layer 1 -> 8). Owner-only:
`require_auth` + `current_user`; cookie writes need `X-Requested-With: JARVIS` (app middleware);
<= 60 changes a minute per owner. Errors are `{error, detail, reason?}`.

GET/PUT /v1/notify/settings   quiet hours, ring_for, per-kind switches, names, snapshot opt-in
                              (`{"snapshot": {"on": true, "confirm": true}}`)
GET/POST/DELETE /v1/notify/vip  phone / email references for R12 (face VIPs live in Faces);
                                GET lists {id, kind, hint} only, never the reference itself
GET /v1/push/key              the VAPID public key
GET /v1/push/devices          {devices:[{id, name, added_at}]}
POST /v1/push/subscribe       {name, endpoint, keys:{p256dh, auth}} -> 201 (422 bad_endpoint)
DELETE /v1/push/subscribe/{id}
POST /v1/push/test            Telegram + this browser

The services are `app.state.notify` and `app.state.push` (None: the feature is off).
"""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.api.ratelimit import RateLimiter
from jarvis.api.settings_audit import record_change
from jarvis.notify.models import (
    DEFAULT_SWITCH,
    HHMM,
    MAX_VIPS,
    NO_SWITCH,
    KindSwitch,
    NotifySettings,
    QuietHours,
    Snapshot,
    Vip,
)
from jarvis.notify.ports import DEFAULT_URGENCY, Signal
from jarvis.notify.service import NotifyService
from jarvis.notify.store import NotifyUnavailable
from jarvis.webpush.endpoints import BAD as BAD_ENDPOINT
from jarvis.webpush.service import BadSubscription, PushService
from jarvis.webpush.store import PushFull, PushUnavailable

CHANGES_PER_MINUTE = 60
NOT_SET_UP = "Alerts aren't set up on this server yet."
router = APIRouter(prefix="/v1", dependencies=[Depends(require_auth)])
_PHONE = re.compile(r"^\+?[0-9][0-9 ()-]{5,20}$")
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,120}\.[^@\s]{2,20}$")


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuietIn(_In):
    on: StrictBool | None = None
    start: str | None = Field(default=None, pattern=HHMM)
    end: str | None = Field(default=None, pattern=HHMM)


class SnapshotIn(_In):
    on: StrictBool
    confirm: StrictBool = False


class SettingsIn(_In):
    quiet: QuietIn | None = None
    ring_for: Literal["important", "urgent"] | None = None
    kinds: dict[str, KindSwitch] | None = None
    names_in_alerts: StrictBool | None = None
    snapshot: SnapshotIn | None = None


class VipIn(_In):
    kind: Literal["phone", "email"]
    ref: str = Field(min_length=1, max_length=200)


class KeysIn(_In):
    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=100)


class SubscribeIn(_In):
    name: str = Field(max_length=200)
    endpoint: str = Field(max_length=2000)
    keys: KeysIn


def _err(status: int, error: str, detail: str, reason: str | None = None) -> JSONResponse:
    body: dict[str, str] = {"error": error, "detail": detail}
    if reason:
        body["reason"] = reason
    return JSONResponse(status_code=status, content=body)


def _notify(request: Request) -> NotifyService | None:
    return getattr(request.app.state, "notify", None)


def _push(request: Request) -> PushService | None:
    return getattr(request.app.state, "push", None)


def _limited(request: Request, uid: str) -> JSONResponse | None:
    if not request.app.state.notify_limit.allow(uid)[0]:
        return _err(429, "rate_limited", "Too many changes; wait a moment.")
    return None


def view(s: NotifySettings) -> dict[str, Any]:
    kinds = {
        k: {
            "switch": s.switch(k),
            "level": DEFAULT_URGENCY[k],
            "fixed": k in NO_SWITCH,
        }
        for k in DEFAULT_URGENCY
        if k != "test"
    }
    return {
        "quiet": s.quiet.model_dump(),
        "ring_for": s.ring_for,
        "kinds": kinds,
        "names_in_alerts": s.names_in_alerts,
        "snapshot": {"on": s.snapshot.on},
        "vip": [{"id": v.id, "kind": v.kind} for v in s.vip],  # references stay server-side
        "vip_max": MAX_VIPS,
    }


@router.get("/notify/settings", response_model=None)
async def get_settings(
    request: Request, svc: NotifyService | None = Depends(_notify), uid: str = Depends(current_user)
) -> Any:
    if svc is None:
        return {"available": False, "reason": NOT_SET_UP}
    s = await svc.store.get(uid)
    return {"available": True, **view(s)}


def _apply(cur: NotifySettings, body: SettingsIn) -> NotifySettings:
    upd: dict[str, Any] = {}
    if body.quiet is not None:
        q = {k: v for k, v in body.quiet.model_dump().items() if v is not None}
        upd["quiet"] = QuietHours.model_validate({**cur.quiet.model_dump(), **q})
    if body.ring_for is not None:
        upd["ring_for"] = body.ring_for
    if body.kinds is not None:
        merged = {**cur.kinds, **body.kinds}
        for k in list(merged):
            if k in NO_SWITCH or merged[k] == DEFAULT_SWITCH.get(k, "on"):
                merged.pop(k)  # no switch, or back to the default: nothing to store
        upd["kinds"] = merged
    if body.names_in_alerts is not None:
        upd["names_in_alerts"] = body.names_in_alerts
    if body.snapshot is not None:
        upd["snapshot"] = Snapshot(
            on=body.snapshot.on, at=datetime.now(UTC).isoformat() if body.snapshot.on else None
        )
    return cur.model_copy(update=upd)


@router.put("/notify/settings", response_model=None)
async def put_settings(
    body: SettingsIn,
    request: Request,
    svc: NotifyService | None = Depends(_notify),
    uid: str = Depends(current_user),
) -> Any:
    if svc is None:
        return _err(503, "unavailable", NOT_SET_UP)
    if (limited := _limited(request, uid)) is not None:
        return limited
    if body.kinds is not None:
        bad = [k for k in body.kinds if k not in DEFAULT_URGENCY or k in NO_SWITCH]
        if bad:
            return _err(422, "bad_kind", "That kind of alert has no switch.")
    if body.snapshot is not None and body.snapshot.on and not body.snapshot.confirm:
        return _err(
            422,
            "confirm_required",
            "Telegram keeps chats on its servers; the photo stays there until you delete the "
            "message. Confirm to switch photos on.",
        )
    try:
        new = await svc.store.update(uid, lambda cur: _apply(cur, body))
    except NotifyUnavailable as exc:
        return _err(503, "unavailable", str(exc))
    except (ValueError, ValidationError):
        return _err(422, "invalid", "Those settings aren't valid.")
    await record_change(
        request,
        agent="alerts",
        tool="notify_settings",
        args={"fields": sorted(body.model_dump(exclude_none=True)), "rev": new.rev},
        detail="alert settings changed",
    )
    return {"available": True, **view(new)}


@router.get("/notify/vip", response_model=None)
async def list_vip(
    svc: NotifyService | None = Depends(_notify), uid: str = Depends(current_user)
) -> Any:
    if svc is None:
        return {"available": False, "reason": NOT_SET_UP, "vip": []}
    s = await svc.store.get(uid)
    # integrated review S6: never the number or address itself, only a hint to tell rows apart
    rows = [{"id": v.id, "kind": v.kind, "hint": _hint(v.kind, v.ref)} for v in s.vip]
    return {"available": True, "vip": rows, "vip_max": MAX_VIPS}


def _hint(kind: str, ref: str) -> str:
    """A phone's last two digits, an address's first letter; nothing for anything else."""
    if kind == "phone":
        digits = [c for c in ref if c.isdigit()]
        return f"ends in {''.join(digits[-2:])}" if len(digits) >= 2 else ""
    if kind == "email" and ref[:1].isalnum():
        return f"{ref[0].lower()}..."
    return ""


@router.post("/notify/vip", response_model=None, status_code=201)
async def add_vip(
    body: VipIn,
    request: Request,
    svc: NotifyService | None = Depends(_notify),
    uid: str = Depends(current_user),
) -> Any:
    if svc is None:
        return _err(503, "unavailable", NOT_SET_UP)
    if (limited := _limited(request, uid)) is not None:
        return limited
    ref = " ".join(body.ref.split())
    if not (_PHONE if body.kind == "phone" else _EMAIL).fullmatch(ref):
        return _err(422, "invalid", f"That doesn't look like a {body.kind}.")
    vip = Vip(id="v_" + secrets.token_hex(4), kind=body.kind, ref=ref.lower())

    def change(cur: NotifySettings) -> NotifySettings:
        if len(cur.vip) >= MAX_VIPS:
            raise ValueError("full")
        if any(v.ref == vip.ref for v in cur.vip):
            return cur
        return cur.model_copy(update={"vip": (*cur.vip, vip)})

    try:
        await svc.store.update(uid, change)
    except NotifyUnavailable as exc:
        return _err(503, "unavailable", str(exc))
    except ValueError:
        return _err(409, "vip_full", f"You can have {MAX_VIPS} people on the list.")
    await record_change(
        request, agent="alerts", tool="notify_vip_add", args={"kind": body.kind}, detail="VIP added"
    )
    return JSONResponse(status_code=201, content={"id": vip.id, "kind": vip.kind})


@router.delete("/notify/vip/{vip_id}", response_model=None)
async def remove_vip(
    vip_id: str,
    request: Request,
    svc: NotifyService | None = Depends(_notify),
    uid: str = Depends(current_user),
) -> Any:
    if svc is None:
        return _err(503, "unavailable", NOT_SET_UP)
    if (limited := _limited(request, uid)) is not None:
        return limited
    found = False

    def change(cur: NotifySettings) -> NotifySettings:
        nonlocal found
        rest = tuple(v for v in cur.vip if v.id != vip_id)
        found = len(rest) != len(cur.vip)
        return cur.model_copy(update={"vip": rest})

    try:
        await svc.store.update(uid, change)
    except NotifyUnavailable as exc:
        return _err(503, "unavailable", str(exc))
    if not found:
        return _err(404, "not_found", "That person isn't on the list.")
    await record_change(
        request, agent="alerts", tool="notify_vip_remove", args={}, detail="VIP removed"
    )
    return {"removed": True}


# ---- Web Push --------------------------------------------------------------------------------


@router.get("/push/key", response_model=None)
async def push_key(svc: PushService | None = Depends(_push)) -> Any:
    if svc is None:
        return {"available": False, "reason": "Browser notifications aren't set up on this server."}
    return {"available": True, "key": svc.public_key}


@router.get("/push/devices", response_model=None)
async def push_devices(
    svc: PushService | None = Depends(_push), uid: str = Depends(current_user)
) -> Any:
    if svc is None:
        return {"available": False, "devices": []}
    try:
        return {"available": True, "devices": [d.view() for d in await svc.devices(uid)]}
    except PushUnavailable as exc:
        return _err(503, "unavailable", str(exc))


@router.post("/push/subscribe", response_model=None, status_code=201)
async def push_subscribe(
    body: SubscribeIn,
    request: Request,
    svc: PushService | None = Depends(_push),
    uid: str = Depends(current_user),
) -> Any:
    if svc is None:
        return _err(503, "unavailable", "Browser notifications aren't set up on this server.")
    if (limited := _limited(request, uid)) is not None:
        return limited
    try:
        dev = await svc.subscribe(
            uid,
            name=body.name,
            endpoint=body.endpoint,
            p256dh=body.keys.p256dh,
            auth=body.keys.auth,
        )
    except BadSubscription as exc:
        kind = "bad_endpoint" if str(exc) == BAD_ENDPOINT else "bad_subscription"
        return _err(422, kind, str(exc))
    except PushFull as exc:
        return _err(409, "push_full", str(exc))
    except PushUnavailable as exc:
        return _err(503, "unavailable", str(exc))
    await record_change(
        request,
        agent="alerts",
        tool="push_subscribe",
        args={"device": dev.id},
        detail="device added",
    )
    return JSONResponse(status_code=201, content=dev.view())


@router.delete("/push/subscribe/{device_id}", response_model=None)
async def push_unsubscribe(
    device_id: str,
    request: Request,
    svc: PushService | None = Depends(_push),
    uid: str = Depends(current_user),
) -> Any:
    if svc is None:
        return _err(503, "unavailable", "Browser notifications aren't set up on this server.")
    try:
        gone = await svc.remove(uid, device_id)
    except PushUnavailable as exc:
        return _err(503, "unavailable", str(exc))
    if not gone:
        return _err(404, "not_found", "That device isn't on the list.")
    await record_change(
        request,
        agent="alerts",
        tool="push_unsubscribe",
        args={"device": device_id},
        detail="device removed",
    )
    return {"removed": True}


@router.post("/push/test", response_model=None)
async def push_test(
    request: Request, svc: NotifyService | None = Depends(_notify), uid: str = Depends(current_user)
) -> Any:
    if svc is None:
        return {"sent": False, "reason": NOT_SET_UP}
    if (limited := _limited(request, uid)) is not None:
        return limited
    d = await svc.notify(
        uid, Signal(source="message", kind="test"), "Test alert from JARVIS. Alerts are working."
    )
    if d.telegram or d.push:
        return {"sent": True, "telegram": d.telegram, "browsers": d.push}
    return {
        "sent": False,
        "telegram": False,
        "browsers": 0,
        "reason": "No channel could deliver it.",
    }


def install_notify(app: FastAPI) -> None:
    """Mount /v1/notify and /v1/push on `app`. Services: `app.state.notify` / `app.state.push`
    (None: the feature is off)."""
    app.state.notify_limit = RateLimiter(CHANGES_PER_MINUTE)

    @app.exception_handler(NotifyUnavailable)
    async def _unavailable(_: Request, exc: NotifyUnavailable) -> JSONResponse:
        return _err(503, "unavailable", str(exc))

    app.include_router(router)


__all__ = ["CHANGES_PER_MINUTE", "install_notify", "router", "view"]
