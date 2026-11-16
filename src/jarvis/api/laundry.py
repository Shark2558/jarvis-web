# src/jarvis/api/laundry.py
"""R13 Part B's routes, under `/v1/laundry` (docs/plans/r13-wardrobe.md "The HTTP contract").

    GET /v1/laundry          the basket, drying, pressing, open loads and outside batches
                             (`wardrobe.http.LaundryView`)
    GET /v1/laundry/review   the review queue: at most 100 open checks and their count
                             (`wardrobe.http.ReviewView`)

Owner-only (`require_auth` + `current_user`), `no-store`, 60 reads a minute per owner
(`api.r13_status.limited`). Part B's service is read per request from
`app.state.r13_parts["laundry"]` (`api.r13_status.part_of`; its `review_writer`'s `desk`). Errors
are `{"detail": <plain words>}`: 503 when Part B is left out or laundry is off (no token key, or
the wardrobe's store isn't there yet). Every change goes through a tool and the gateway
(`POST /v1/wardrobe/tools/{tool}`, Part A's route): these two routes only read.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.api.r13_status import NO_STORE, limited, part_of
from jarvis.wardrobe.laundry.store import LaundryUnavailable
from jarvis.wardrobe.laundry.texts import NOT_SET_UP

router = APIRouter(dependencies=[Depends(require_auth)])


def _desk(request: Request) -> Any:
    part = part_of(request, "laundry")
    writer = part.services.get("review_writer") if part is not None else None
    return getattr(writer, "desk", None)


def _unavailable(words: str) -> JSONResponse:
    return JSONResponse({"detail": words}, status_code=503, headers=NO_STORE)


async def _answer(request: Request, uid: str, route: str, read: str) -> JSONResponse:
    if (busy := limited(request, route, uid, change=False)) is not None:
        return busy
    desk = _desk(request)
    if desk is None:
        return _unavailable(NOT_SET_UP)
    try:
        body = await getattr(desk, read)(uid)
    except LaundryUnavailable as exc:
        return _unavailable(str(exc))
    return JSONResponse(body.model_dump(mode="json"), headers=NO_STORE)


@router.get("/v1/laundry", include_in_schema=False)
async def laundry(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    return await _answer(request, uid, "GET /v1/laundry", "laundry_view")


@router.get("/v1/laundry/review", include_in_schema=False)
async def laundry_review(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    return await _answer(request, uid, "GET /v1/laundry/review", "review_view")


__all__ = ["router"]
