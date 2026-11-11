# src/jarvis/api/helpers_kitchen.py
"""R11 Part D's routes, under `/v1/helpers/kitchen` (docs/plans/r11-free-helpers.md D2, D19): the
Kitchen tab. Owner-only (`require_auth` + `current_user`; cookie writes need
`X-Requested-With: JARVIS`), `no-store`, changes rate-limited per owner (I0's limiter). They read
the part's service from `app.state.r11_parts["kitchen"].services` per request.

GET    /v1/helpers/kitchen                   the tab's view (pantry, tastes, recipes, blocks,
                                             grocery spend, nutrition status)
POST   /v1/helpers/kitchen/pantry            {add?: [name], remove?: [name]}
PUT    /v1/helpers/kitchen/prefs             {diet?, spice?, oil?, cuisines?: [name], note?}
DELETE /v1/helpers/kitchen/recipes/{id}      a saved recipe
PUT    /v1/helpers/kitchen/spend             {on: bool}: read his grocery receipts or not
POST   /v1/helpers/kitchen/spend/scan        read them now (his permission rows still decide)
PUT    /v1/helpers/kitchen/blocks            {cooking_at?, cooking_minutes?, washing_at?,
                                             washing_minutes?, days?: [mon..sun]}: the plan
POST   /v1/helpers/kitchen/blocks/propose    the plan as an approval card through the gateway
                                             (`calendar_kitchen_blocks`); nothing is written here

404 {error: "helpers_off"} when the part is off; 422 {error: "invalid", detail}; 429; 503
{error: "unavailable"} when the kitchen can't be read; 200 {sealed: false, detail} without a key.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.api.ratelimit import RateLimiter
from jarvis.helpers.kitchen.blocks import TOOL as BLOCKS_TOOL
from jarvis.helpers.kitchen.models import Diet
from jarvis.helpers.kitchen.part import SERVICE
from jarvis.helpers.kitchen.service import KitchenService
from jarvis.helpers.kitchen.store import KitchenOff, KitchenUnavailable
from jarvis.llm.base import ToolCall
from jarvis.logging import get_logger
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.taint import context_trust

log = get_logger(__name__)

PREFIX = "/v1/helpers/kitchen"
NO_STORE = {"Cache-Control": "no-store"}
router = APIRouter(prefix=PREFIX, dependencies=[Depends(require_auth)])


class PantryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    add: list[str] = Field(default_factory=list, max_length=50)
    remove: list[str] = Field(default_factory=list, max_length=50)


class PrefsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    diet: Diet | None = None
    spice: StrictInt | None = None
    oil: StrictInt | None = None
    cuisines: list[str] | None = Field(default=None, max_length=6)
    note: str | None = Field(default=None, max_length=400)


class SpendBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    on: StrictBool


class BlocksBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cooking_at: str | None = Field(default=None, max_length=5)
    cooking_minutes: StrictInt | None = None
    washing_at: str | None = Field(default=None, max_length=5)
    washing_minutes: StrictInt | None = None
    days: list[str] | None = Field(default=None, max_length=7)


def _answer(status: int, body: dict[str, Any]) -> JSONResponse:
    return JSONResponse(status_code=status, content=body, headers=NO_STORE)


def _service(request: Request) -> KitchenService | None:
    parts = getattr(request.app.state, "r11_parts", None) or {}
    part = parts.get("kitchen")
    found = part.services.get(SERVICE) if part is not None else None
    return found if isinstance(found, KitchenService) else None


def _off() -> JSONResponse:
    return _answer(404, {"error": "helpers_off", "detail": "The kitchen helper is off."})


async def _view(svc: KitchenService, uid: str) -> JSONResponse:
    try:
        return _answer(200, await svc.view(uid))
    except KitchenOff as exc:
        return _answer(200, {"sealed": False, "detail": str(exc)})
    except KitchenUnavailable as exc:
        return _answer(503, {"error": "unavailable", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001 - plain words, the class in the log
        log.warning("kitchen view failed", extra={"error": type(exc).__name__})
        return _answer(503, {"error": "unavailable", "detail": "Couldn't read the kitchen."})


Work = Callable[[KitchenService], Awaitable[Any]]


async def _change(request: Request, uid: str, work: Work) -> JSONResponse:
    svc = _service(request)
    if svc is None:
        return _off()
    limiter: RateLimiter | None = getattr(request.app.state, "helpers_limit", None)
    if limiter is not None and not limiter.allow(uid)[0]:
        return _answer(429, {"error": "rate_limited", "detail": "Too many changes; wait a moment."})
    try:
        got = await work(svc)
    except (KitchenOff, KitchenUnavailable) as exc:
        return _answer(503, {"error": "unavailable", "detail": str(exc)})
    except LookupError as exc:
        return _answer(404, {"error": "not_found", "detail": str(exc)})
    except ValueError as exc:
        return _answer(422, {"error": "invalid", "detail": _plain(exc)})
    except Exception as exc:  # noqa: BLE001 - the store; plain words
        log.warning("kitchen not changed", extra={"error": type(exc).__name__})
        return _answer(503, {"error": "unavailable", "detail": "Couldn't save that just now."})
    if isinstance(got, JSONResponse):
        return got
    return await _view(svc, uid)


def _plain(exc: ValueError) -> str:
    """Our own words; a pydantic error becomes one fixed line (it may quote the input)."""
    text = str(exc)
    return "Check what you typed and try again." if "validation error" in text else text


@router.get("", response_model=None)
async def kitchen_get(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    svc = _service(request)
    return _off() if svc is None else await _view(svc, uid)


@router.post("/pantry", response_model=None)
async def kitchen_pantry(
    request: Request, body: PantryBody, uid: str = Depends(current_user)
) -> JSONResponse:
    async def work(svc: KitchenService) -> None:
        if body.add:
            await _ok(svc.add(uid, body.add))
        if body.remove:
            await _ok(svc.remove(uid, body.remove))

    return await _change(request, uid, work)


async def _ok(got: Awaitable[dict[str, Any]]) -> None:
    out = await got
    if out.get("unavailable"):
        raise KitchenUnavailable()


@router.put("/prefs", response_model=None)
async def kitchen_prefs(
    request: Request, body: PrefsBody, uid: str = Depends(current_user)
) -> JSONResponse:
    async def work(svc: KitchenService) -> None:
        await _ok(svc.settings(uid, body.model_dump(exclude_none=True), tainted=False))

    return await _change(request, uid, work)


@router.delete("/recipes/{rid}", response_model=None)
async def kitchen_forget(
    request: Request, rid: str, uid: str = Depends(current_user)
) -> JSONResponse:
    async def work(svc: KitchenService) -> None:
        if not await svc.forget_recipe(uid, rid[:40]):
            raise LookupError("No saved recipe with that id.")

    return await _change(request, uid, work)


@router.put("/spend", response_model=None)
async def kitchen_spend(
    request: Request, body: SpendBody, uid: str = Depends(current_user)
) -> JSONResponse:
    async def work(svc: KitchenService) -> None:
        await svc.spend.set_on(uid, body.on)

    return await _change(request, uid, work)


@router.post("/spend/scan", response_model=None)
async def kitchen_scan(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    async def work(svc: KitchenService) -> JSONResponse | None:
        if svc.job is None:
            return _answer(
                409, {"error": "off", "detail": "Link Google and keep a token key first."}
            )
        outcome = await svc.job.scan_one(uid)
        if outcome != "ok":
            words = {
                "off": "Receipts are off.",
                "skipped": "Your Email or Kitchen row doesn't allow it.",
            }
            return _answer(409, {"error": outcome, "detail": words.get(outcome, "Not read.")})
        return None

    return await _change(request, uid, work)


@router.put("/blocks", response_model=None)
async def kitchen_blocks(
    request: Request, body: BlocksBody, uid: str = Depends(current_user)
) -> JSONResponse:
    async def work(svc: KitchenService) -> None:
        await svc.set_blocks(uid, body.model_dump(exclude_none=True))

    return await _change(request, uid, work)


@router.post("/blocks/propose", response_model=None)
async def kitchen_propose(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    gateway: Gateway | None = getattr(request.app.state, "gateway", None)

    async def work(svc: KitchenService) -> JSONResponse:
        if gateway is None or not svc.calendar:
            return _answer(409, {"error": "off", "detail": "Link Google to add calendar blocks."})
        plan = (await svc.store.load(uid)).blocks
        args: dict[str, Any] = {
            "cooking_at": plan.cooking_at,
            "cooking_minutes": plan.cooking_minutes,
            "washing_at": plan.washing_at,
            "washing_minutes": plan.washing_minutes,
            "days": ",".join(plan.days) or "daily",
        }
        call = ToolCall(id=f"kitchen-{uuid.uuid4().hex[:8]}", name=BLOCKS_TOOL, arguments=args)
        with context_trust(untrusted=False):  # the owner's own button and his own saved plan
            res = await gateway.execute(call, scope=f"{uid}:helpers_kitchen")
        if res.outcome is not GatewayOutcome.AWAITING_CONFIRMATION or res.pending is None:
            return _answer(409, {"error": "not_proposed", "detail": "The card couldn't be made."})
        return _answer(200, {"pending": True, "message": res.pending.summary})

    return await _change(request, uid, work)


__all__ = ["PREFIX", "router"]
