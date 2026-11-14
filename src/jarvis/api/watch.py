# src/jarvis/api/watch.py
"""R7 Part D's watch and sleep routes, under `/v1/watch` (docs/plans/r7-mobile.md D17, D18).
Owner-only (`require_auth` + `current_user`; cookie writes need `X-Requested-With: JARVIS`),
`no-store`, writes rate-limited per owner. The phone's sums arrive by the signed door
(`/phone/v1/health`, Part C's door, Part D's handler), never here.

GET  /v1/watch          {part, ready, enabled, sealed, last_synced, kinds, today, last_night,
                         week} (Helpers -> Watch); without a token key {.., sealed: false, note}
POST /v1/watch/sleep    {start "HH:MM", end "HH:MM"}: a night he typed -> {message, night}
                         | 422 {error: invalid, detail} | 503 {error: watch_off | unavailable}
Errors are JARVIS's own plain words; no value is ever logged.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.api.mobile_status import NO_STORE, part_of
from jarvis.api.ratelimit import RateLimiter
from jarvis.mobile.ports import NOT_BUILT, PartName
from jarvis.watch.service import NoteRefused, WatchService
from jarvis.watch.store import WatchOff, WatchUnavailable
from jarvis.watch.words import noted_words

PART: PartName = "body"
WRITES_PER_MINUTE = 20
router = APIRouter(prefix="/v1/watch", dependencies=[Depends(require_auth)])
_writes = RateLimiter(WRITES_PER_MINUTE)


class SleepBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: str = Field(max_length=5)
    end: str = Field(max_length=5)


def _json(body: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers=NO_STORE)


def _service(request: Request) -> tuple[str, WatchService | None]:
    part = part_of(request, PART)
    svc = part.services.get("watch") if part is not None else None
    return (part.ready if part is not None else NOT_BUILT), (
        svc if isinstance(svc, WatchService) else None
    )


@router.get("", include_in_schema=False)
async def watch_view(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    ready, svc = _service(request)
    head: dict[str, Any] = {"part": PART, "ready": ready}
    if svc is None:
        return _json(head)
    if not svc.sealed:
        return _json({**head, "enabled": svc.enabled, "sealed": False, "note": WatchOff.WORDS})
    try:
        return _json({**head, **await svc.view(uid)})
    except WatchUnavailable:
        return _json({**head, "error": "unavailable", "detail": WatchUnavailable.WORDS}, 503)


@router.post("/sleep", include_in_schema=False)
async def watch_sleep(
    body: SleepBody, request: Request, uid: str = Depends(current_user)
) -> JSONResponse:
    _, svc = _service(request)
    if svc is None or not svc.enabled:
        return _json({"error": "watch_off", "detail": "Watch data is switched off, Sir."}, 503)
    allowed, _ = _writes.allow(uid)
    if not allowed:
        return _json({"error": "busy", "detail": "Too many changes at once, Sir."}, 429)
    try:
        night = await svc.note(uid, body.start, body.end)
    except NoteRefused as exc:
        return _json({"error": "invalid", "detail": str(exc)}, 422)
    except (WatchOff, WatchUnavailable) as exc:
        code = "watch_off" if isinstance(exc, WatchOff) else "unavailable"
        return _json({"error": code, "detail": str(exc)}, 503)
    return _json(
        {
            "message": noted_words(night),
            "night": {
                "minutes": night.minutes,
                "start": night.start,
                "end": night.end,
                "source": night.source,
            },
        }
    )


__all__ = ["PART", "router"]
