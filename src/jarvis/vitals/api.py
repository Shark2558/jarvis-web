# src/jarvis/vitals/api.py
"""The Vitals panel over HTTP (R4). Owner-only: `require_auth` + `current_user` (the user id is
never taken from the client; a browser write needs `X-Requested-With: JARVIS`, enforced by
require_auth).

GET    /v1/vitals              {overall, items: [ProviderView json],
                                spend: {used_inr, limit_inr, text}|null}
PUT    /v1/vitals/keys         Provider body (manual) -> {saved}; 422 plain `detail`
DELETE /v1/vitals/keys/{id}    -> {removed: true}; 404 when no such manual record

The integrator sets `app.state.vitals` (a `VitalsService`, or None -> 503) and `app.include_router`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.vitals.models import Provider
from jarvis.vitals.service import VitalsService
from jarvis.vitals.store import VitalsFull, VitalsUnavailable

router = APIRouter(prefix="/v1/vitals", dependencies=[Depends(require_auth)])
NOT_AVAILABLE = "Vitals is not available on this server."


def _svc(request: Request) -> VitalsService:
    svc = getattr(request.app.state, "vitals", None)
    if svc is None:
        raise HTTPException(503, NOT_AVAILABLE)
    return svc  # type: ignore[no-any-return]


@router.get("")
async def board(
    svc: VitalsService = Depends(_svc), uid: str = Depends(current_user)
) -> dict[str, Any]:
    try:
        return (await svc.board(uid)).to_json()
    except VitalsUnavailable as exc:
        raise HTTPException(503, str(exc)) from None


@router.put("/keys")
async def put_key(
    p: Provider, svc: VitalsService = Depends(_svc), uid: str = Depends(current_user)
) -> dict[str, str]:
    try:
        await svc.set_key(uid, p)
    except (ValueError, VitalsFull) as exc:
        raise HTTPException(422, str(exc)) from None
    except VitalsUnavailable as exc:
        raise HTTPException(503, str(exc)) from None
    return {"saved": p.id}


@router.delete("/keys/{pid}")
async def delete_key(
    pid: str, svc: VitalsService = Depends(_svc), uid: str = Depends(current_user)
) -> dict[str, bool]:
    try:
        removed = await svc.delete_key(uid, pid)
    except (ValueError, VitalsUnavailable) as exc:
        raise HTTPException(503, str(exc)) from None
    if not removed:
        raise HTTPException(404, "No such tracked key.")
    return {"removed": True}


__all__ = ["router"]
