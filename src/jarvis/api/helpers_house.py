# src/jarvis/api/helpers_house.py
"""R11 Part B's routes, under `/v1/helpers/house` (docs/plans/r11-free-helpers.md D2, D10-D14, D19).

Owner-only (`require_auth` + `current_user`; cookie writes need `X-Requested-With: JARVIS`),
`no-store`, every change rate-limited per owner (I0's `app.state.helpers_limit`) and answered
with the whole Home view. Thin: everything is `helpers.house.service.HouseService`, read from
`app.state.r11_parts["house"].services["house"]` per request.

GET    /v1/helpers/house                    the Home tab's view
POST   /v1/helpers/house/chores             {label, freq, at?, days?, every?, members?}
POST   /v1/helpers/house/chores/{id}/done   mark it done today (the rota turns)
DELETE /v1/helpers/house/chores/{id}
POST   /v1/helpers/house/upkeep             {label, every, unit?, last_done?, lead?}
POST   /v1/helpers/house/upkeep/{id}/done
DELETE /v1/helpers/house/upkeep/{id}
PUT    /v1/helpers/house/place              {district, state, lat?, lon?, lgd?, thresholds?}
DELETE /v1/helpers/house/place              weather and disaster alerts off again
PUT    /v1/helpers/house/breach             {on}: he has subscribed at HIBP "Notify me"

404 {error: "helpers_off"} when the part is off; 409 {error: "off"} for his place without a
keyring; 422 {error: "invalid", detail} in plain words; 429 rate_limited; 503 unavailable.
Nothing here sends a message or reads anything outside JARVIS.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, ValidationError

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.api.ratelimit import RateLimiter
from jarvis.helpers.house.models import MAX_MEMBERS, Place, Thresholds
from jarvis.helpers.house.service import HouseService
from jarvis.helpers.house.store import OutsideOff
from jarvis.logging import get_logger

log = get_logger(__name__)

PREFIX = "/v1/helpers/house"
NO_STORE = {"Cache-Control": "no-store"}
router = APIRouter(prefix=PREFIX, dependencies=[Depends(require_auth)])


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChoreBody(_Body):
    label: str = Field(max_length=200)
    freq: Literal["daily", "weekly", "every"]
    at: str = Field(default="09:00", max_length=5)
    days: list[str] = Field(default_factory=list, max_length=7)
    every: StrictInt | None = None
    members: list[str] = Field(default_factory=list, max_length=MAX_MEMBERS)


class UpkeepBody(_Body):
    label: str = Field(max_length=200)
    every: StrictInt
    unit: Literal["days", "months"] = "days"
    last_done: date | None = None
    lead: StrictInt = 7


class PlaceBody(_Body):
    district: str = Field(max_length=80)
    state: str = Field(max_length=80)
    lat: float | None = None
    lon: float | None = None
    lgd: str | None = Field(default=None, max_length=6)
    thresholds: dict[str, float] | None = Field(default=None, max_length=4)


class BreachBody(_Body):
    on: StrictBool


def _answer(status: int, body: dict[str, Any]) -> JSONResponse:
    return JSONResponse(status_code=status, content=body, headers=NO_STORE)


def _service(request: Request) -> HouseService | None:
    parts = getattr(request.app.state, "r11_parts", None) or {}
    part = parts.get("house")
    svc = part.services.get("house") if part is not None else None
    return svc if isinstance(svc, HouseService) else None


def _off(request: Request) -> JSONResponse:
    why = getattr(request.app.state, "helpers_off", None) or "off"
    return _answer(404, {"error": "helpers_off", "detail": f"The helpers are off ({why})."})


async def _view(svc: HouseService, uid: str) -> JSONResponse:
    try:
        return _answer(200, await svc.view(uid))
    except Exception as exc:  # noqa: BLE001 - plain words, the class in the log
        log.warning("house view failed", extra={"error": type(exc).__name__})
        return _answer(503, {"error": "unavailable", "detail": "Couldn't read Home just now."})


def _plain(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        errors = exc.errors()
        if not errors:
            return "That isn't valid."
        return str(errors[0]["msg"]).removeprefix("Value error, ")
    return str(exc)


async def _change(
    request: Request, uid: str, work: Callable[[HouseService], Awaitable[Any]]
) -> JSONResponse:
    svc = _service(request)
    if svc is None:
        return _off(request)
    limiter: RateLimiter | None = getattr(request.app.state, "helpers_limit", None)
    if limiter is not None and not limiter.allow(uid)[0]:
        return _answer(429, {"error": "rate_limited", "detail": "Too many changes; wait a moment."})
    try:
        await work(svc)
    except OutsideOff as exc:
        return _answer(409, {"error": "off", "detail": str(exc)})
    except ValueError as exc:  # a pydantic ValidationError is a ValueError too
        return _answer(422, {"error": "invalid", "detail": _plain(exc)})
    except Exception as exc:  # noqa: BLE001 - the store; plain words
        log.warning("house change failed", extra={"error": type(exc).__name__})
        return _answer(503, {"error": "unavailable", "detail": "Couldn't save that just now."})
    return await _view(svc, uid)


@router.get("", response_model=None)
async def house_get(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    svc = _service(request)
    return _off(request) if svc is None else await _view(svc, uid)


@router.post("/chores", response_model=None)
async def chore_add(
    request: Request, body: ChoreBody, uid: str = Depends(current_user)
) -> JSONResponse:
    async def work(svc: HouseService) -> None:
        await svc.add_chore(
            uid,
            label=body.label,
            freq=body.freq,
            at=body.at,
            days=body.days,
            every=body.every,
            members=body.members,
        )

    return await _change(request, uid, work)


@router.post("/chores/{cid}/done", response_model=None)
async def chore_done(request: Request, cid: str, uid: str = Depends(current_user)) -> JSONResponse:
    async def work(svc: HouseService) -> None:
        await svc.chore_done(uid, cid)

    return await _change(request, uid, work)


@router.delete("/chores/{cid}", response_model=None)
async def chore_remove(
    request: Request, cid: str, uid: str = Depends(current_user)
) -> JSONResponse:
    async def work(svc: HouseService) -> None:
        await svc.remove_chore(uid, cid)

    return await _change(request, uid, work)


@router.post("/upkeep", response_model=None)
async def upkeep_add(
    request: Request, body: UpkeepBody, uid: str = Depends(current_user)
) -> JSONResponse:
    async def work(svc: HouseService) -> None:
        await svc.add_upkeep(
            uid,
            label=body.label,
            every=body.every,
            unit=body.unit,
            last_done=body.last_done,
            lead=body.lead,
        )

    return await _change(request, uid, work)


@router.post("/upkeep/{cid}/done", response_model=None)
async def upkeep_done(request: Request, cid: str, uid: str = Depends(current_user)) -> JSONResponse:
    async def work(svc: HouseService) -> None:
        await svc.upkeep_done(uid, cid)

    return await _change(request, uid, work)


@router.delete("/upkeep/{cid}", response_model=None)
async def upkeep_remove(
    request: Request, cid: str, uid: str = Depends(current_user)
) -> JSONResponse:
    async def work(svc: HouseService) -> None:
        await svc.remove_upkeep(uid, cid)

    return await _change(request, uid, work)


@router.put("/place", response_model=None)
async def place_set(
    request: Request, body: PlaceBody, uid: str = Depends(current_user)
) -> JSONResponse:
    async def work(svc: HouseService) -> None:
        place = Place(
            district=body.district, state=body.state, lat=body.lat, lon=body.lon, lgd=body.lgd
        )
        th = Thresholds(**body.thresholds) if body.thresholds is not None else None
        await svc.set_place(uid, place, th)

    return await _change(request, uid, work)


@router.delete("/place", response_model=None)
async def place_clear(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    async def work(svc: HouseService) -> None:
        await svc.clear_place(uid)

    return await _change(request, uid, work)


@router.put("/breach", response_model=None)
async def breach_set(
    request: Request, body: BreachBody, uid: str = Depends(current_user)
) -> JSONResponse:
    async def work(svc: HouseService) -> None:
        await svc.set_breach(uid, body.on)

    return await _change(request, uid, work)


__all__ = ["PREFIX", "router"]
