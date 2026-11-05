# src/jarvis/health/api.py
"""The Systems panel's routes (R4 D6). Owner-only: the integrator passes `require_auth` as a
dependency and `current_user` as `user`, exactly as the other /v1 routers get them.

GET  /v1/health        last stored result {overall|null, spoken, checked_at, systems[]}
POST /v1/health/run    run the probes now (no model call; a result under 30 s old is reused),
                       answers the same shape. run and speak: 10/min per owner, then 429
POST /v1/health/speak  audio/mpeg of the last result's fixed line; 409 before any check, 503 when
                       the voice is unavailable
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import JSONResponse

from jarvis.api.ratelimit import RateLimiter
from jarvis.health.models import HealthReport
from jarvis.health.tools import view
from jarvis.voice.ports import VoiceError, VoiceUnavailable

RUN_PER_MINUTE = (
    10  # run + speak share one per-owner budget, inside the router so it is never skipped
)


def _empty() -> dict[str, Any]:
    return {"overall": None, "spoken": "", "checked_at": None, "systems": []}


class HealthLike(Protocol):
    """What the routes need of a health service (`HealthService`, or the app's live stand-in)."""

    async def last(self, uid: str) -> HealthReport | None: ...

    async def check(self, uid: str, *, force: bool = False) -> HealthReport: ...

    async def speak(self, uid: str) -> Any | None: ...


def health_router(
    svc: HealthLike,
    *,
    user: Callable[..., str],
    dependencies: Sequence[Any] = (),
) -> APIRouter:
    router = APIRouter(prefix="/v1/health", dependencies=list(dependencies))
    limiter = RateLimiter(RUN_PER_MINUTE)

    def limited(uid: str = Depends(user)) -> str:
        allowed, retry_s = limiter.allow(uid)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail={"error": "rate_limited", "detail": "Too many requests; wait a moment."},
                headers={"Retry-After": str(max(1, math.ceil(retry_s)))},
            )
        return uid

    @router.get("")
    async def last(uid: str = Depends(user)) -> dict[str, Any]:
        report = await svc.last(uid)
        return _empty() if report is None else view(report)

    @router.post("/run")
    async def run(uid: str = Depends(limited)) -> dict[str, Any]:
        return view(await svc.check(uid))

    @router.post("/speak", response_class=Response)
    async def speak(uid: str = Depends(limited)) -> Response:
        if await svc.last(uid) is None:
            return JSONResponse(
                {"error": "nothing_to_say", "detail": "Run a systems check first."}, status_code=409
            )
        try:
            out = await svc.speak(uid)
        except VoiceUnavailable:  # the vendor's reason is never echoed
            return JSONResponse(
                {"error": "voice_unavailable", "detail": "The voice is not available."},
                status_code=503,
            )
        except VoiceError:
            return JSONResponse(
                {"error": "voice_failed", "detail": "The voice could not speak."}, status_code=422
            )
        if out is None:
            return JSONResponse(
                {"error": "voice_unavailable", "detail": "The voice is not set up."},
                status_code=503,
            )
        return Response(
            content=out.audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store"}
        )

    return router


__all__ = ["health_router"]
