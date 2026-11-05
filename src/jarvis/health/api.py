# src/jarvis/health/api.py
"""The Systems panel's routes (R4 D6). Owner-only: the integrator passes `require_auth` as a
dependency and `current_user` as `user`, exactly as the other /v1 routers get them.

GET  /v1/health        last stored result {overall|null, spoken, checked_at, systems[]}
POST /v1/health/run    run the probes now (no model call), answers the same shape
POST /v1/health/speak  audio/mpeg of the last result's fixed line; 409 before any check, 503 when
                       the voice is unavailable
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse

from jarvis.health.service import HealthService
from jarvis.health.tools import view
from jarvis.voice.ports import VoiceError, VoiceUnavailable

EMPTY: dict[str, Any] = {"overall": None, "spoken": "", "checked_at": None, "systems": []}


def health_router(
    svc: HealthService,
    *,
    user: Callable[..., str],
    dependencies: Sequence[Any] = (),
) -> APIRouter:
    router = APIRouter(prefix="/v1/health", dependencies=list(dependencies))

    @router.get("")
    async def last(uid: str = Depends(user)) -> dict[str, Any]:
        report = await svc.last(uid)
        return EMPTY if report is None else view(report)

    @router.post("/run")
    async def run(uid: str = Depends(user)) -> dict[str, Any]:
        return view(await svc.check(uid))

    @router.post("/speak", response_class=Response)
    async def speak(uid: str = Depends(user)) -> Response:
        if await svc.last(uid) is None:
            return JSONResponse(
                {"error": "nothing_to_say", "detail": "Run a systems check first."}, status_code=409
            )
        try:
            out = await svc.speak(uid)
        except VoiceUnavailable as exc:
            return JSONResponse(
                {
                    "error": "voice_unavailable",
                    "detail": "The voice is not available.",
                    "reason": exc.reason,
                },
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
