# src/jarvis/api/r13_status.py
"""R13 I0: `GET /v1/r13` and the helpers every R13 part's routes share.

    GET /v1/r13   {version, parts: [{part, ready}]}   (`wardrobe.http.R13Status`) ready: "not
                  built yet" until the part is built, "setup failed" when the wiring left it out

Owner-only (`require_auth`), `no-store`. A part's routes read its services from
`app.state.r13_parts[<part>].services` per request (`part_of`); `limited` gives each route its
own per-owner allowance (the plan's 30 changes and 60 reads a minute) beside the app-wide limit.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from jarvis import __version__
from jarvis.api.auth import require_auth
from jarvis.api.ratelimit import RateLimiter
from jarvis.wardrobe.http import R13Status, Ready
from jarvis.wardrobe.ports import NOT_BUILT, PARTS, R13_STATUS_ROUTE, PartName, WardrobePart

NO_STORE = {"Cache-Control": "no-store"}
CHANGES_PER_MINUTE, READS_PER_MINUTE = 30, 60
LIMITS_STATE = "r13_limits"
LIMITED = {"error": "rate_limited", "detail": "Too many requests; wait a minute."}
router = APIRouter(dependencies=[Depends(require_auth)])


def limited(
    request: Request, route: str, uid: str, *, change: bool, per: int | None = None
) -> JSONResponse | None:
    """A 429 when `uid` is past this route's allowance, else None. `per`: a route's own tighter
    allowance a minute (R13.1: `POST /v1/seeme/pictures`, 6), else R13's 30 changes or 60 reads."""
    limits = getattr(request.app.state, LIMITS_STATE, None)
    if not isinstance(limits, dict):
        limits = {}
        setattr(request.app.state, LIMITS_STATE, limits)
    if per is None:
        per = CHANGES_PER_MINUTE if change else READS_PER_MINUTE
    limiter = limits.setdefault(route, RateLimiter(per))
    allowed, wait = limiter.allow(uid)
    if allowed:
        return None
    retry = {"Retry-After": str(max(1, int(wait + 0.999)))}
    return JSONResponse(LIMITED, status_code=429, headers=NO_STORE | retry)


def part_of(request: Request, name: PartName) -> WardrobePart | None:
    parts: dict[str, Any] = getattr(request.app.state, "r13_parts", None) or {}
    return parts.get(name)


def ready_of(request: Request, name: PartName) -> str:
    part = part_of(request, name)
    return part.ready if part is not None else NOT_BUILT


@router.get(R13_STATUS_ROUTE, include_in_schema=False)
async def r13_status(request: Request) -> JSONResponse:
    body = R13Status(
        version=f"v{__version__}",
        parts=tuple(Ready(part=n, ready=ready_of(request, n)) for n in PARTS),
    )
    return JSONResponse(body.model_dump(mode="json"), headers=NO_STORE)


__all__ = ["NO_STORE", "limited", "part_of", "ready_of", "router"]
