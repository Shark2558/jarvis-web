# src/jarvis/api/backup.py
"""R14 Part A's routes, under `/v1/backup` (docs/plans/r14-hardening.md D4). Owner-only
(`require_auth` + `current_user`; cookie writes need `X-Requested-With`), `no-store`.

GET  /v1/backup         {part, ready}  (I0's stub; Part A adds the facts: set up, last copy, size,
                        the last drill's result)
POST /v1/backup/drill   the same card as "test my backup" (`vitals_drill_start`, R2, never part of
                        Approve all), rate-limited per owner; I0's stub: 501 {error: not_built}
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.api.r14_status import NO_STORE, ready_of, status_route
from jarvis.hardening.ports import NOT_BUILT, PartName

PART: PartName = "backup"
router = APIRouter(prefix="/v1/backup", dependencies=[Depends(require_auth)])
router.add_api_route("", status_route(PART), methods=["GET"], include_in_schema=False)


@router.post("/drill", include_in_schema=False)
async def drill(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    ready = ready_of(request, PART)
    body = {"error": "not_built", "detail": f"The restore drill is {NOT_BUILT}.", "ready": ready}
    return JSONResponse(body, status_code=501, headers=NO_STORE)


__all__ = ["router"]
