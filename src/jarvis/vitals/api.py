# src/jarvis/vitals/api.py
"""The Vitals panel over HTTP (R4). Owner-only: `require_auth` + `current_user` (the user id is
never taken from the client; a browser write needs `X-Requested-With: JARVIS`, enforced by
require_auth).

GET    /v1/vitals              {overall, items: [ProviderView json],
                                spend: {used_inr, limit_inr, text}|null}
PUT    /v1/vitals/keys         Provider body (manual) -> {saved}; 422 plain `detail`;
                                with `"create": true` an id that exists answers 409 (never replaced)
DELETE /v1/vitals/keys/{id}    -> {removed: true}; 404 when no such manual record

The integrator sets `app.state.vitals` (a `VitalsService`, or None -> 503) and `app.include_router`.
"""

from __future__ import annotations

import math
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.api.ratelimit import RateLimiter
from jarvis.vitals.models import Provider, describe_error
from jarvis.vitals.service import VitalsService
from jarvis.vitals.store import BAD_ID, VitalsExists, VitalsFull, VitalsUnavailable, valid_id

router = APIRouter(prefix="/v1/vitals", dependencies=[Depends(require_auth)])
NOT_AVAILABLE = "Vitals is not available on this server."


GET_PER_MINUTE = 30
WRITE_PER_MINUTE = 10  # PUT + DELETE share one per-owner budget (R5.1 int-sec M3)


def _limited(request: Request, uid: str = Depends(current_user)) -> str:
    """Per-owner limit on the board read (it fans out to several stores). The limiter lives on
    the app (`app.state.vitals_limiter`, made on first use), so no wiring is needed."""
    state = request.app.state
    limiter = getattr(state, "vitals_limiter", None)
    if limiter is None:
        limiter = state.vitals_limiter = RateLimiter(GET_PER_MINUTE)
    allowed, retry_s = limiter.allow(uid)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={"error": "rate_limited", "detail": "Too many requests; wait a moment."},
            headers={"Retry-After": str(max(1, math.ceil(retry_s)))},
        )
    return uid


def _write_limited(request: Request, uid: str = Depends(current_user)) -> str:
    """Per-owner limit on the writes (each drops the board cache and touches the store)."""
    state = request.app.state
    limiter = getattr(state, "vitals_write_limiter", None)
    if limiter is None:
        limiter = state.vitals_write_limiter = RateLimiter(WRITE_PER_MINUTE)
    allowed, retry_s = limiter.allow(uid)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={"error": "rate_limited", "detail": "Too many requests; wait a moment."},
            headers={"Retry-After": str(max(1, math.ceil(retry_s)))},
        )
    return uid


def _svc(request: Request) -> VitalsService:
    svc = getattr(request.app.state, "vitals", None)
    if svc is None:
        raise HTTPException(503, NOT_AVAILABLE)
    return svc  # type: ignore[no-any-return]


@router.get("")
async def board(svc: VitalsService = Depends(_svc), uid: str = Depends(_limited)) -> dict[str, Any]:
    try:
        return (await svc.board_cached(uid)).to_json()
    except VitalsUnavailable as exc:
        raise HTTPException(503, str(exc)) from None


@router.put("/keys")
async def put_key(
    request: Request, svc: VitalsService = Depends(_svc), uid: str = Depends(_write_limited)
) -> dict[str, str]:
    # The body is read and validated here (not by FastAPI) so a 422 can never echo the input: a
    # pasted key value must not come back in an error body or a log line.
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(422, "The request body must be a JSON object.") from None
    if not isinstance(body, dict):
        raise HTTPException(422, "The request body must be a JSON object.")
    create = body.pop("create", False) is True  # a NEW item: never replace an existing one
    try:
        p = Provider.model_validate({**body, "source": "manual"})
    except ValidationError as exc:
        raise HTTPException(422, describe_error(exc)) from None
    try:
        await svc.set_key(uid, p, create=create)
    except VitalsExists as exc:
        raise HTTPException(409, str(exc)) from None
    except (ValueError, VitalsFull) as exc:
        raise HTTPException(422, str(exc)) from None
    except VitalsUnavailable as exc:
        raise HTTPException(503, str(exc)) from None
    return {"saved": p.id}


@router.delete("/keys/{pid}")
async def delete_key(
    pid: str, svc: VitalsService = Depends(_svc), uid: str = Depends(_write_limited)
) -> dict[str, bool]:
    if not valid_id(pid):
        raise HTTPException(422, BAD_ID)
    try:
        removed = await svc.delete_key(uid, pid)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except VitalsUnavailable as exc:
        raise HTTPException(503, str(exc)) from None
    if not removed:
        raise HTTPException(404, "No such tracked key.")
    return {"removed": True}


__all__ = ["router"]
