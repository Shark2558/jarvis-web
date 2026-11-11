# src/jarvis/api/helpers_nudges.py
"""R11 Part C's routes, under `/v1/helpers/nudges` (docs/plans/r11-free-helpers.md D2, D6, D19): the
Nudges tab. Owner-only (`require_auth` + `current_user`; cookie writes need `X-Requested-With:
JARVIS`), `no-store`, changes rate-limited per owner (I0's limiter). The part's service is read from
`app.state.r11_parts["nudges"].services` per request.

GET    /v1/helpers/nudges                 {enabled, sealed, calendar, nudges: [...], gate: {snoozed,
                                          stopped, today}, today: {water, stood} | null, ideas}
PUT    /v1/helpers/nudges/{name}          {on?, every?, start?, end?, days?, times?, meeting?,
                                          word?, words?} (name: standup, water, activity,
                                          free_time, focus) -> the view
POST   /v1/helpers/nudges/water           {glasses: 1..10} -> the view (409 with no token key)
POST   /v1/helpers/nudges/stood           a stand-up -> the view (409 with no token key)
POST   /v1/helpers/nudges/ideas           {text, minutes, place} -> the view
POST   /v1/helpers/nudges/ideas/{id}/done -> the view
DELETE /v1/helpers/nudges/ideas/{id}      -> the view (404 when it isn't on the list)

Snooze, stop and resume are I0's taps (`/v1/helpers/gate/{kind}/...`). 404 {error: "helpers_off"}
when the part is off; 422 {error: "invalid", detail} in plain words; 503 {error: "unavailable"}.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.api.ratelimit import RateLimiter
from jarvis.helpers.nudges import hydrate
from jarvis.helpers.nudges.models import LABEL, NAME, NUDGE_KINDS, Idea, NudgeSettings, Place
from jarvis.helpers.nudges.service import NudgeService
from jarvis.helpers.nudges.store import WellbeingOff
from jarvis.helpers.nudges.words import describe, when
from jarvis.logging import get_logger

log = get_logger(__name__)

PREFIX = "/v1/helpers/nudges"
NO_STORE = {"Cache-Control": "no-store"}
_BY_NAME = {v: k for k, v in NAME.items()}
router = APIRouter(prefix=PREFIX, dependencies=[Depends(require_auth)])


class NudgeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    on: StrictBool | None = None
    every: StrictInt | None = None
    start: str | None = Field(default=None, max_length=5)
    end: str | None = Field(default=None, max_length=5)
    days: list[StrictInt] | None = Field(default=None, max_length=7)
    times: list[str] | None = Field(default=None, max_length=6)
    meeting: StrictBool | None = None
    word: str | None = Field(default=None, max_length=30)
    words: list[str] | None = Field(default=None, max_length=10)


class WaterBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    glasses: StrictInt = 1


class IdeaBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(max_length=200)
    minutes: StrictInt = 30
    place: Place = "any"


class _Missing(LookupError):
    pass


def _answer(status: int, body: dict[str, Any]) -> JSONResponse:
    return JSONResponse(status_code=status, content=body, headers=NO_STORE)


def _service(request: Request) -> NudgeService | None:
    parts = getattr(request.app.state, "r11_parts", None) or {}
    part = parts.get("nudges")
    svc = part.services.get("service") if part is not None else None
    return svc if isinstance(svc, NudgeService) else None


def _off(request: Request) -> JSONResponse:
    why = getattr(request.app.state, "helpers_off", None) or "off"
    return _answer(404, {"error": "helpers_off", "detail": f"The nudges are off ({why})."})


def _nudge(kind: str, s: NudgeSettings) -> dict[str, Any]:
    n = s.nudge(kind)
    return {
        "kind": kind,
        "name": NAME[kind],
        "label": LABEL[kind],
        **n.model_dump(mode="json"),
        "line": describe(kind, n),
        "when": when(kind, n),
    }


async def view(svc: NudgeService, uid: str) -> dict[str, Any]:
    s, gate, day = await svc.settings(uid), await svc.gate.state(uid), svc.day_of().isoformat()
    today = None
    if svc.well.on:
        logged = await svc.well.day(uid, day)
        today = {"water": logged.water, "stood": logged.stood}
    return {
        "enabled": True,
        "sealed": svc.well.on,
        "calendar": svc.agenda.linked,
        "nudges": [_nudge(k, s) for k in NUDGE_KINDS],
        "gate": {"snoozed": dict(gate.snoozed), "stopped": dict(gate.stopped), "today": day},
        "today": today,
        "ideas": [i.model_dump(mode="json") for i in s.ideas],
    }


async def _act(
    request: Request, uid: str, work: Callable[[NudgeService], Awaitable[Any]] | None
) -> JSONResponse:
    svc = _service(request)
    if svc is None:
        return _off(request)
    if work is not None:
        limiter: RateLimiter | None = getattr(request.app.state, "helpers_limit", None)
        if limiter is not None and not limiter.allow(uid)[0]:
            return _answer(429, {"error": "rate_limited", "detail": "Too many changes; wait."})
    try:
        if work is not None:
            await work(svc)
        return _answer(200, await view(svc, uid))
    except WellbeingOff as exc:
        return _answer(409, {"error": "sealed_off", "detail": str(exc)})
    except _Missing as exc:
        return _answer(404, {"error": "not_found", "detail": str(exc)})
    except ValueError as exc:
        return _answer(422, {"error": "invalid", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001 - the store; plain words, the class in the log
        log.warning("nudges route failed", extra={"error": type(exc).__name__})
        return _answer(503, {"error": "unavailable", "detail": "Couldn't reach your nudges."})


@router.get("", response_model=None)
async def nudges_get(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    return await _act(request, uid, None)


@router.put("/{name}", response_model=None)
async def nudges_put(
    request: Request, name: str, body: NudgeBody, uid: str = Depends(current_user)
) -> JSONResponse:
    async def work(svc: NudgeService) -> None:
        kind = _BY_NAME.get(name)
        if kind is None:
            raise ValueError("Unknown nudge.")
        changes = body.model_dump(exclude_none=True)
        if not changes:
            raise ValueError("Nothing to change.")
        await svc.store.change(uid, lambda s: s.changed(kind, changes))

    return await _act(request, uid, work)


@router.post("/water", response_model=None)
async def nudges_water(
    request: Request, body: WaterBody, uid: str = Depends(current_user)
) -> JSONResponse:
    async def work(svc: NudgeService) -> None:
        await hydrate.log_water(svc, uid, body.glasses)

    return await _act(request, uid, work)


@router.post("/stood", response_model=None)
async def nudges_stood(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    async def work(svc: NudgeService) -> None:
        await hydrate.log_stood(svc, uid)

    return await _act(request, uid, work)


@router.post("/ideas", response_model=None)
async def ideas_add(
    request: Request, body: IdeaBody, uid: str = Depends(current_user)
) -> JSONResponse:
    async def work(svc: NudgeService) -> None:
        idea = Idea.new(body.text, body.minutes, body.place)
        await svc.store.change(uid, lambda s: s.with_idea(idea))

    return await _act(request, uid, work)


def _without(s: NudgeSettings, idea_id: str) -> NudgeSettings:
    if not any(i.id == idea_id for i in s.ideas):
        raise _Missing("That idea isn't on your list.")
    return s.with_ideas(tuple(i for i in s.ideas if i.id != idea_id))


@router.delete("/ideas/{idea_id}", response_model=None)
async def ideas_remove(
    request: Request, idea_id: str, uid: str = Depends(current_user)
) -> JSONResponse:
    async def work(svc: NudgeService) -> None:
        await svc.store.change(uid, lambda s: _without(s, idea_id))

    return await _act(request, uid, work)


@router.post("/ideas/{idea_id}/done", response_model=None)
async def ideas_done(
    request: Request, idea_id: str, uid: str = Depends(current_user)
) -> JSONResponse:
    async def work(svc: NudgeService) -> None:
        today = svc.day_of().isoformat()

        def mark(s: NudgeSettings) -> NudgeSettings:
            if not any(i.id == idea_id for i in s.ideas):
                raise _Missing("That idea isn't on your list.")
            done = tuple(
                i.model_copy(update={"last_done": today}) if i.id == idea_id else i for i in s.ideas
            )
            return s.with_ideas(done)

        await svc.store.change(uid, mark)

    return await _act(request, uid, work)


__all__ = ["PREFIX", "router", "view"]
