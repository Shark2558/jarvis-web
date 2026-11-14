# src/jarvis/api/vision.py
"""R7 Part B's routes, under `/v1/vision` (docs/plans/r7-mobile.md D12-D14). Owner-only
(`require_auth` + `current_user`; cookie writes need `X-Requested-With: JARVIS`), `no-store`,
changes rate-limited per owner. A picture never comes here: only results, at most 64 KB of JSON.

GET    /v1/vision                  {part, ready, release, sealed, keep_days, tasks: {name:
                                   {installed, why}}}: `pose` and `objects` say "not installed"
                                   until their model files are served (`jarvis.vision.assets`)
GET    /v1/vision/results?days=7&limit=200&offset=0
                                   {sealed, keep_days, results: [...], total, more, unreadable}
                                   newest first (1-365 days); `unreadable`: days that did not open
POST   /v1/vision/results          one Result he pressed Keep on -> 201 {kept}
DELETE /v1/vision/results/{id}     one kept result -> {deleted: true}

404 {error: "vision_off"} when the part is off; 422 {error: "dropped"} for a result outside its
task's schema (never repaired, nothing stored); 409 {error: "not_sealed"} without a token key;
413 {error: "too_large"}; 429 {error: "rate_limited"}; 503 {error: "unavailable"}. The read
path reads the part's service from `app.state.r7_parts["vision"].services` per request.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from jarvis.api.auth import require_auth
from jarvis.api.body import BodyTooLarge, read_capped, too_large_body
from jarvis.api.console import vision_files
from jarvis.api.identity import current_user
from jarvis.api.mobile_status import NO_STORE, part_of
from jarvis.logging import get_logger
from jarvis.mobile.ports import NOT_BUILT, PartName
from jarvis.vision import assets
from jarvis.vision.part import SERVICE, VisionService
from jarvis.vision.store import (
    RESULT_ID,
    DayFull,
    Dropped,
    VisionOff,
    VisionStore,
    VisionUnavailable,
)

log = get_logger(__name__)

PART: PartName = "vision"
RESULT_BODY_MAX = 64 * 1024
PAGE_MAX = 200  # results in one answer (a long keep would otherwise send thousands)
OFF = {"error": "vision_off", "detail": "Kept camera results are off on this server."}
LIMITED = {"error": "rate_limited", "detail": "Too many changes; wait a moment."}
UNAVAILABLE = "Your kept camera results couldn't be read just now, Sir."
router = APIRouter(prefix="/v1/vision", dependencies=[Depends(require_auth)])


def _answer(status: int, body: dict[str, Any]) -> JSONResponse:
    return JSONResponse(status_code=status, content=body, headers=NO_STORE)


def _service(request: Request) -> VisionService | None:
    part = part_of(request, PART)
    found = part.services.get(SERVICE) if part is not None else None
    return found if isinstance(found, VisionService) else None


@router.get("", include_in_schema=False)
async def vision_status(request: Request) -> JSONResponse:
    part = part_of(request, PART)
    svc = _service(request)
    served = vision_files(assets.RELEASE)
    tasks = {
        task: {"installed": ok, "why": assets.why(task, served)}
        for task, ok in assets.installed(served).items()
    }
    return _answer(
        200,
        {
            "part": PART,
            "ready": part.ready if part is not None else NOT_BUILT,
            "release": assets.RELEASE,
            "sealed": bool(svc and svc.store.sealed),
            "keep_days": svc.store.keep_days if svc else 0,
            "tasks": tasks,
        },
    )


@router.get("/results", response_model=None)
async def vision_results(
    request: Request,
    days: int = Query(default=7, ge=1, le=365),
    limit: int = Query(default=PAGE_MAX, ge=1, le=PAGE_MAX),
    offset: int = Query(default=0, ge=0, le=100_000),
    uid: str = Depends(current_user),
) -> JSONResponse:
    svc = _service(request)
    if svc is None:
        return _answer(404, OFF)
    store = svc.store
    base = {"sealed": store.sealed, "keep_days": store.keep_days}
    try:
        page = await store.page(uid, days=days, limit=limit, offset=offset)
        more = offset + len(page.items) < page.total
        body = {**base, "results": page.items, "total": page.total, "more": more}
        return _answer(200, {**body, "unreadable": page.unreadable})
    except VisionOff as exc:
        return _answer(200, {**base, "results": [], "detail": str(exc)})
    except VisionUnavailable as exc:
        return _answer(503, {"error": "unavailable", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001 - plain words, the class in the log
        log.warning("kept vision results not read", extra={"error": type(exc).__name__})
        return _answer(503, {"error": "unavailable", "detail": UNAVAILABLE})


Work = Callable[[VisionStore], Awaitable[JSONResponse]]


async def _change(request: Request, uid: str, work: Work) -> JSONResponse:
    svc = _service(request)
    if svc is None:
        return _answer(404, OFF)
    if not svc.limit.allow(uid)[0]:
        return _answer(429, LIMITED)
    try:
        return await work(svc.store)
    except VisionOff as exc:
        return _answer(409, {"error": "not_sealed", "detail": str(exc)})
    except Dropped as exc:
        return _answer(422, {"error": "dropped", "detail": str(exc)})
    except DayFull as exc:
        return _answer(409, {"error": "day_full", "detail": str(exc)})
    except VisionUnavailable as exc:
        return _answer(503, {"error": "unavailable", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001 - the store; plain words
        log.warning("kept vision results not changed", extra={"error": type(exc).__name__})
        return _answer(503, {"error": "unavailable", "detail": "Couldn't save that just now."})


def _too_large() -> BodyTooLarge:
    return BodyTooLarge(RESULT_BODY_MAX)


@router.post("/results", response_model=None)
async def vision_keep(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    try:
        body = await read_capped(request, RESULT_BODY_MAX, too_large=_too_large)
    except BodyTooLarge as exc:
        return _answer(413, too_large_body(str(exc.detail)))

    async def work(store: VisionStore) -> JSONResponse:
        try:
            raw = json.loads(body)
        except ValueError:
            raise Dropped() from None
        return _answer(201, {"kept": await store.keep(uid, raw)})

    return await _change(request, uid, work)


@router.delete("/results/{rid}", response_model=None)
async def vision_forget(
    request: Request, rid: str, uid: str = Depends(current_user)
) -> JSONResponse:
    async def work(store: VisionStore) -> JSONResponse:
        if RESULT_ID.match(rid) and await store.delete(uid, rid):
            return _answer(200, {"deleted": True})
        return _answer(404, {"error": "not_found", "detail": "No kept result with that id."})

    return await _change(request, uid, work)


__all__ = ["PART", "RESULT_BODY_MAX", "router"]
