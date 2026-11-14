# src/jarvis/api/r14_status.py
"""R14 I0: the parts' status, for every R14 part's route stub, and `GET /v1/r14`.

    GET /v1/r14   {parts: {backup, selfwatch, skills, noai: ready}}   ready: "not built yet" until
                  the part is built, "setup failed" when the wiring left it out

Owner-only (`require_auth`), `no-store`. A part's routes read its services from
`app.state.r14_parts[<part>].services` per request (`part_of`).

`read_limited` (R14 I1, security review LOW-5): each status read (`GET /v1/backup`,
`/v1/selfwatch`, `/v1/skills`, `/v1/costs/ledger`, 1 to 31 Firestore reads each) has its own
per-owner allowance of `READS_PER_MINUTE`, per process like `POST /v1/backup/drill`'s, beside the
app-wide limit.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from jarvis.api.auth import require_auth
from jarvis.api.ratelimit import RateLimiter
from jarvis.hardening.ports import NOT_BUILT, PARTS, R14_STATUS_ROUTE, HardeningPart, PartName

NO_STORE = {"Cache-Control": "no-store"}
READS_PER_MINUTE = 30
LIMITS_STATE = "r14_read_limits"
LIMITED = {"error": "rate_limited", "detail": "Too many requests; wait a minute."}
router = APIRouter(dependencies=[Depends(require_auth)])


def read_limited(request: Request, route: str, uid: str) -> JSONResponse | None:
    """A 429 when `uid` is past this route's allowance, else None."""
    limits = getattr(request.app.state, LIMITS_STATE, None)
    if not isinstance(limits, dict):
        limits = {}
        setattr(request.app.state, LIMITS_STATE, limits)
    limiter = limits.setdefault(route, RateLimiter(READS_PER_MINUTE))
    allowed, wait = limiter.allow(uid)
    if allowed:
        return None
    retry = {"Retry-After": str(max(1, int(wait + 0.999)))}
    return JSONResponse(LIMITED, status_code=429, headers=NO_STORE | retry)


def part_of(request: Request, name: PartName) -> HardeningPart | None:
    parts: dict[str, Any] = getattr(request.app.state, "r14_parts", None) or {}
    return parts.get(name)


def ready_of(request: Request, name: PartName) -> str:
    part = part_of(request, name)
    return part.ready if part is not None else NOT_BUILT


def status_route(name: PartName) -> Callable[[Request], Awaitable[JSONResponse]]:
    async def status(request: Request) -> JSONResponse:
        return JSONResponse({"part": name, "ready": ready_of(request, name)}, headers=NO_STORE)

    status.__name__ = f"r14_{name}_status"
    return status


@router.get(R14_STATUS_ROUTE, include_in_schema=False)
async def r14_status(request: Request) -> JSONResponse:
    return JSONResponse({"parts": {n: ready_of(request, n) for n in PARTS}}, headers=NO_STORE)


__all__ = [
    "NO_STORE",
    "READS_PER_MINUTE",
    "part_of",
    "read_limited",
    "ready_of",
    "router",
    "status_route",
]
