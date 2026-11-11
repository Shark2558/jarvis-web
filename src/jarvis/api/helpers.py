# src/jarvis/api/helpers.py
"""R11 I0 routes (docs/plans/r11-free-helpers.md D3, D6, D19, D21): the Helpers panel's frame and
the nudge limits. Owner-only (`require_auth` + `current_user`; cookie writes need
`X-Requested-With: JARVIS`), `no-store`, changes rate-limited per owner.

GET  /v1/helpers                      {enabled, off?, parts: [{name, tab, ready}], clock:
                                      {last_run, stale, jobs}, nudges: {kinds, caps, defaults,
                                      max_per_day, max_per_hour, snoozed, stopped, today},
                                      fortnight: {reminders_on_time, reminders_late, ...}}
PUT  /v1/helpers/gate                 {caps: {nudge kind: 0..24}} -> the same view
POST /v1/helpers/gate/{kind}/snooze   {minutes: 15..720} (kind: a nudge kind or "all")
POST /v1/helpers/gate/{kind}/stop     stop it for the rest of today
POST /v1/helpers/gate/{kind}/resume   undo a snooze or a stop

404 {error: "helpers_off"} when the helpers are off; 422 {error: "invalid", detail} in plain words;
503 {error: "unavailable"} when the nudge state can't be read or changed. Nothing here sends.
The parts' own routes live in `api/helpers_<part>.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.api.ratelimit import RateLimiter
from jarvis.helpers.gate import ALL, GateUnavailable, HelperSender, NudgeState, fortnight
from jarvis.helpers.kinds import DEFAULT_CAPS, NUDGE_KINDS, PARTS, TABS
from jarvis.logging import get_logger

log = get_logger(__name__)

CHANGES_PER_MINUTE = 30
STALE_AFTER = timedelta(minutes=12)  # two missed 5-minute runs (D3)
NO_STORE = {"Cache-Control": "no-store"}
_TARGET: dict[str, str] = {"all": ALL, **{str(k): str(k) for k in NUDGE_KINDS}}
router = APIRouter(prefix="/v1/helpers", dependencies=[Depends(require_auth)])


def change_limiter() -> RateLimiter:
    """The per-owner limit on changes; `install_r11_routes` puts one on `app.state`."""
    return RateLimiter(CHANGES_PER_MINUTE)


class CapsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    caps: dict[str, StrictInt] = Field(max_length=len(NUDGE_KINDS))


class SnoozeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    minutes: StrictInt


def _answer(status: int, body: dict[str, Any]) -> JSONResponse:
    return JSONResponse(status_code=status, content=body, headers=NO_STORE)


def _sender(request: Request) -> HelperSender | None:
    return getattr(request.app.state, "helpers_sender", None)


def _now(request: Request) -> datetime:
    return request.app.state.helpers_now()  # type: ignore[no-any-return]


def _off(request: Request) -> JSONResponse:
    why = getattr(request.app.state, "helpers_off", None) or "off"
    return _answer(404, {"error": "helpers_off", "detail": f"The helpers are off ({why})."})


async def _clock(request: Request) -> dict[str, Any]:
    status = getattr(request.app.state, "helpers_status", None)
    got = await status.read() if status is not None else None
    at = got.get("at") if isinstance(got, dict) else None
    try:
        last = datetime.fromisoformat(at) if isinstance(at, str) else None
    except ValueError:
        last = None
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    stale = last is None or _now(request) - last > STALE_AFTER
    jobs = got.get("jobs") if isinstance(got, dict) else None
    return {"last_run": at if last else None, "stale": stale, "jobs": jobs or {}}


def _nudges(state: NudgeState, sends: list[dict[str, str]], s: Any) -> dict[str, Any]:
    today = {
        k: sum(1 for e in sends if e.get("k") == k and e.get("o") in ("rang", "silent"))
        for k in NUDGE_KINDS
    }
    return {
        "kinds": list(NUDGE_KINDS),
        "caps": {k: state.cap(k) for k in NUDGE_KINDS},
        "defaults": dict(DEFAULT_CAPS),
        "max_per_day": s.nudges_max_per_day,
        "max_per_hour": s.nudges_max_per_hour,
        "snoozed": dict(state.snoozed),
        "stopped": dict(state.stopped),
        "today": today,
    }


async def _view(request: Request, uid: str) -> dict[str, Any]:
    sender = _sender(request)
    assert sender is not None
    s, parts = request.app.state.settings, getattr(request.app.state, "r11_parts", {})
    day = sender.today(_now(request))
    state = await sender.store.state(uid)
    days = await sender.store.days(uid)
    sends = next((x for d, x in days if d == day), [])
    return {
        "enabled": True,
        "parts": [
            {"name": p, "tab": TABS[p], "ready": parts[p].ready if p in parts else "off"}
            for p in PARTS
        ],
        "clock": await _clock(request),
        "nudges": _nudges(state, sends, s),
        "fortnight": fortnight(days, day, max_per_day=s.nudges_max_per_day),
    }


async def _respond(request: Request, uid: str) -> JSONResponse:
    try:
        return _answer(200, await _view(request, uid))
    except GateUnavailable as exc:
        return _answer(503, {"error": "unavailable", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001 - plain words, the class in the log
        log.warning("helpers view failed", extra={"error": type(exc).__name__})
        return _answer(503, {"error": "unavailable", "detail": "Couldn't read the helpers."})


@router.get("", response_model=None)
async def helpers_get(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    if _sender(request) is None:
        why = getattr(request.app.state, "helpers_off", None) or "off"
        return _answer(200, {"enabled": False, "off": why})
    return await _respond(request, uid)


async def _change(request: Request, uid: str, work: Any) -> JSONResponse:
    if _sender(request) is None:
        return _off(request)
    limiter: RateLimiter | None = getattr(request.app.state, "helpers_limit", None)
    if limiter is not None and not limiter.allow(uid)[0]:
        return _answer(429, {"error": "rate_limited", "detail": "Too many changes; wait a moment."})
    try:
        await work()
    except ValueError as exc:
        return _answer(422, {"error": "invalid", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001 - the store; plain words
        log.warning("nudge state not changed", extra={"error": type(exc).__name__})
        return _answer(503, {"error": "unavailable", "detail": "Couldn't save that just now."})
    return await _respond(request, uid)


def _target(kind: str) -> str:
    if kind not in _TARGET:
        raise ValueError("Unknown nudge.")
    return _TARGET[kind]


@router.put("/gate", response_model=None)
async def gate_caps(
    request: Request, body: CapsBody, uid: str = Depends(current_user)
) -> JSONResponse:
    async def work() -> None:
        sender = _sender(request)
        assert sender is not None
        await sender.store.set_caps(uid, body.caps)

    return await _change(request, uid, work)


@router.post("/gate/{kind}/snooze", response_model=None)
async def gate_snooze(
    request: Request, kind: str, body: SnoozeBody, uid: str = Depends(current_user)
) -> JSONResponse:
    async def work() -> None:
        sender = _sender(request)
        assert sender is not None
        await sender.store.snooze(uid, _target(kind), body.minutes, _now(request))

    return await _change(request, uid, work)


@router.post("/gate/{kind}/stop", response_model=None)
async def gate_stop(request: Request, kind: str, uid: str = Depends(current_user)) -> JSONResponse:
    async def work() -> None:
        sender = _sender(request)
        assert sender is not None
        await sender.store.stop_today(uid, _target(kind), sender.today(_now(request)))

    return await _change(request, uid, work)


@router.post("/gate/{kind}/resume", response_model=None)
async def gate_resume(
    request: Request, kind: str, uid: str = Depends(current_user)
) -> JSONResponse:
    async def work() -> None:
        sender = _sender(request)
        assert sender is not None
        await sender.store.resume(uid, _target(kind))

    return await _change(request, uid, work)


__all__ = ["CHANGES_PER_MINUTE", "STALE_AFTER", "change_limiter", "router"]
