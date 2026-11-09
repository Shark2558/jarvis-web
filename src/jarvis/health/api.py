# src/jarvis/health/api.py
"""The Systems routes (R4 D6; R5.1 D5/D7/D8). Owner-only: the integrator passes `require_auth` as a
dependency and `current_user` as `user`, exactly as the other /v1 routers get them (so the cookie
CSRF header rule applies to every POST here).

GET  /v1/health             last stored result {overall|null, spoken, checked_at, systems[],
                            briefing{spoken, lines[], concerns[]}}; `spoken` stays the R4
                            one-line summary, `briefing.spoken` is the full R5.1 briefing
POST /v1/health/run         run the probes now (no model call; a result under 30 s old is reused),
                            answers the same shape
POST /v1/health/run/stream  {force?: bool} -> application/x-ndjson: plan, result per probe as it
                            completes, done (the same shape + briefing); a run in flight is
                            joined, not repeated (429 when it has no room for another listener);
                            404 where the service can't stream (the console falls back to /run)
POST /v1/health/speak       audio/mpeg of the last result's fixed line; 409 before any check, 503
                            when the voice is unavailable
POST /v1/health/remind      {key, when: 1h|evening|tomorrow, session_id?} -> {outcome, line}: a
                            reminder for one of the last check's concerns, through the gateway
                            (`jarvis.health.remind`); 422 for a key that is not a current concern
run, run/stream, speak and remind share one per-owner budget (10/min, then 429), inside the
router so wiring can never skip it.
"""

from __future__ import annotations

import json
import math
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, StrictBool

from jarvis.api.ratelimit import RateLimiter
from jarvis.health.briefing import EMPTY, Briefing, compose_briefing
from jarvis.health.models import HealthReport
from jarvis.health.remind import RemindBody, RemindDeps, RemindMemo, deps_from_app, set_reminder
from jarvis.health.report import view
from jarvis.health.service import STREAM_FAILED, CheckBusy
from jarvis.logging import get_logger
from jarvis.voice.ports import VoiceError, VoiceUnavailable

log = get_logger(__name__)

RUN_PER_MINUTE = 10  # run + stream + speak + remind share one per-owner budget, inside the router
NDJSON = "application/x-ndjson"
NO_STREAM = "Streaming isn't available here."
RUNNING = "A check is already running, Sir. Wait a moment."
UNKNOWN_CONCERN = "That isn't one of the things the last check found."


def _empty() -> dict[str, Any]:
    return {
        "overall": None,
        "spoken": "",
        "checked_at": None,
        "systems": [],
        "briefing": EMPTY.to_json(),
    }


class HealthLike(Protocol):
    """What the routes need of a health service (`HealthService`, or the app's live stand-in).
    `briefing` and `check_stream` (R5.1) are optional: without them the briefing has no vitals
    and the stream answers 404."""

    async def last(self, uid: str) -> HealthReport | None: ...

    async def check(self, uid: str, *, force: bool = False) -> HealthReport: ...

    async def speak(self, uid: str) -> Any | None: ...


class RunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    force: StrictBool = False  # the pop-up forces past the 30 s cooldown


async def briefing_of(svc: HealthLike, uid: str, report: HealthReport | None) -> Briefing:
    if report is None:
        return EMPTY
    fn = getattr(svc, "briefing", None)
    if fn is None:
        return compose_briefing(report, None)
    brief: Briefing = await fn(uid, report)
    return brief


async def _answer(svc: HealthLike, uid: str, report: HealthReport | None) -> dict[str, Any]:
    if report is None:
        return _empty()
    out = view(report)
    out["briefing"] = (await briefing_of(svc, uid, report)).to_json()
    return out


def health_router(
    svc: HealthLike,
    *,
    user: Callable[..., str],
    dependencies: Sequence[Any] = (),
    remind_deps: Callable[[Request], RemindDeps] | None = None,
) -> APIRouter:
    """`remind_deps`: the gateway, Google and the owner's zone for /remind; by default read live
    from `request.app.state` (`gateway`, `google`, `settings.user_timezone`)."""
    router = APIRouter(prefix="/v1/health", dependencies=list(dependencies))
    limiter = RateLimiter(RUN_PER_MINUTE)
    memo = RemindMemo()

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
        return await _answer(svc, uid, await svc.last(uid))

    @router.post("/run")
    async def run(uid: str = Depends(limited)) -> dict[str, Any]:
        return await _answer(svc, uid, await svc.check(uid))

    @router.post("/run/stream", response_class=StreamingResponse)
    async def run_stream(body: RunBody | None = None, uid: str = Depends(limited)) -> Response:
        stream = getattr(svc, "check_stream", None)
        if stream is None:
            raise HTTPException(404, {"error": "not_available", "detail": NO_STREAM})
        try:
            events: AsyncIterator[dict[str, Any]] = stream(uid, force=bool(body and body.force))
        except CheckBusy:
            raise HTTPException(
                429,
                {"error": "check_running", "detail": RUNNING},
                headers={"Retry-After": "5"},
            ) from None

        async def lines() -> AsyncIterator[str]:
            try:
                async for event in events:
                    yield json.dumps(event, ensure_ascii=False) + "\n"
            except Exception as exc:  # noqa: BLE001 - the stream ends in fixed words
                log.error("health stream route failed", extra={"error": type(exc).__name__})
                yield json.dumps({"type": "error", "detail": STREAM_FAILED}) + "\n"

        return StreamingResponse(
            lines(),
            media_type=NDJSON,
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

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

    @router.post("/remind")
    async def remind(
        body: RemindBody, request: Request, uid: str = Depends(limited)
    ) -> dict[str, str]:
        brief = await briefing_of(svc, uid, await svc.last(uid))
        concern = next((c for c in brief.concerns if c.key == body.key), None)
        if concern is None:
            raise HTTPException(422, {"error": "unknown_concern", "detail": UNKNOWN_CONCERN})
        deps = remind_deps(request) if remind_deps is not None else deps_from_app(request.app)
        answer = await set_reminder(
            deps, uid, concern, body.when, session_id=body.session_id, memo=memo
        )
        return answer.to_json()

    return router


__all__ = ["NDJSON", "RUN_PER_MINUTE", "RunBody", "briefing_of", "health_router"]
