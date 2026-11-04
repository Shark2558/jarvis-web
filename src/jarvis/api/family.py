# src/jarvis/api/family.py
"""Family calendars (R1 D15; Layer 1 -> 6). Owner-only: `require_auth` + `current_user` (no client
user id is read); cookie writes need `X-Requested-With: JARVIS` (enforced by `require_auth`).

GET    /v1/family       {configured: false}  -- no Google link service on this server, or
                        {configured: true, members: [{id, name, calendar_id, access, can_write,
                        added_at}], max_members: 8, how_to: "..."}
POST   /v1/family       {name, calendar_id} -> 201 member. Verifies with Google first (the calendar
                        must be shared with the owner). Errors {error, detail}: 422 invalid /
                        not_shared ("Not shared with you yet -- ask them: ..."), 409 full /
                        duplicate, 503 not_connected / unavailable, 429 rate_limited.
DELETE /v1/family/{id}  -> {removed: id}; 404 not_found.
Google's own text never appears. Each change is one audit entry (agent "family", a hash of the
calendar address only). Nothing here writes to a family calendar: that is the R3 tool.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.api.ratelimit import RateLimiter
from jarvis.api.settings_audit import record_change
from jarvis.family.models import MAX_MEMBERS, view
from jarvis.family.service import FamilyError, FamilyService
from jarvis.logging import get_logger

log = get_logger(__name__)

CHANGES_PER_MINUTE = 20
HOW_TO = (
    "Ask each person to open Google Calendar -> Settings -> Share with specific people and add "
    "your Gmail address, then add their calendar address here."
)
_MEMBER_ID = re.compile(r"fam_[0-9a-f]{12}")
router = APIRouter(prefix="/v1/family", dependencies=[Depends(require_auth)])


class AddBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: StrictStr = Field(max_length=200)
    calendar_id: StrictStr = Field(max_length=400)


def _svc(request: Request) -> FamilyService | None:
    return getattr(request.app.state, "family", None)


def _err(status: int, error: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": error, "detail": detail})


def _limited(request: Request, uid: str) -> JSONResponse | None:
    allowed, _ = request.app.state.family_limit.allow(uid)
    return None if allowed else _err(429, "rate_limited", "Too many changes; wait a moment.")


@router.get("")
async def family_view(
    svc: FamilyService | None = Depends(_svc), uid: str = Depends(current_user)
) -> dict[str, Any]:
    if svc is None:
        return {"configured": False}
    members = await svc.members(uid)
    return {
        "configured": True,
        "members": [view(m).model_dump() for m in members],
        "max_members": MAX_MEMBERS,
        "how_to": HOW_TO,
    }


@router.post("", status_code=201, response_model=None)
async def family_add(
    body: AddBody,
    request: Request,
    svc: FamilyService | None = Depends(_svc),
    uid: str = Depends(current_user),
) -> dict[str, Any] | JSONResponse:
    if svc is None:
        return _err(404, "family_off", "Family calendars need the Google link on this server.")
    if (limited := _limited(request, uid)) is not None:
        return limited
    try:
        member = await svc.add(uid, body.name, body.calendar_id)
    except FamilyError as exc:
        return _err(exc.status, exc.reason, exc.detail)
    log.info("family calendar added", extra={"access": member.access})  # never the address
    await record_change(
        request,
        agent="family",
        tool="family_member_add",
        args={"calendar": member.calendar_id},
        detail=member.access,
    )
    return view(member).model_dump()


@router.delete("/{member_id}", response_model=None)
async def family_remove(
    member_id: str,
    request: Request,
    svc: FamilyService | None = Depends(_svc),
    uid: str = Depends(current_user),
) -> dict[str, Any] | JSONResponse:
    if svc is None:
        return _err(404, "family_off", "Family calendars need the Google link on this server.")
    if (limited := _limited(request, uid)) is not None:
        return limited
    if not _MEMBER_ID.fullmatch(member_id) or not await svc.remove(uid, member_id):
        return _err(404, "not_found", "That family calendar isn't in your list.")
    await record_change(
        request, agent="family", tool="family_member_remove", args={"member": member_id}
    )
    return {"removed": member_id}


def install_family(app: FastAPI) -> None:
    """Mount /v1/family and its per-owner change limit on `app`. The service itself is
    `app.state.family` (a FamilyService, from `tools.r1_tools.build_family_service`)."""
    app.state.family_limit = RateLimiter(CHANGES_PER_MINUTE)
    app.include_router(router)


__all__ = ["CHANGES_PER_MINUTE", "install_family", "router"]
