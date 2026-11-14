# src/jarvis/api/backup.py
"""R14 Part A's routes, under `/v1/backup` (docs/plans/r14-hardening.md D4). Owner-only
(`require_auth` + `current_user`; cookie writes need `X-Requested-With`), `no-store`. They read the
part's desk from `app.state.r14_parts["backup"].services["backup"]` per request.

GET  /v1/backup        {part, ready, set_up, schedule, last_copy, copies, size_mb, documents,
                       month_inr, drill, drill_at, drill_running, spoken}: counts and times only
                       (`tools.BackupDesk.summary`, what `vitals_backups` says)
POST /v1/backup/drill  {session_id} -> 202 {status: "awaiting", approval_id, card, detail}: the
                       SAME card as "test my backup" (`vitals_drill_start` through the gateway,
                       in his own conversation: his Permissions row and the audit chain apply; R2,
                       never part of Approve all). 409 without a conversation of his, 403 when his
                       row says Never, 429 past `DRILL_PER_MINUTE` a minute per owner, 503 when
                       the tools are off. It restores nothing: the approved card asks for a drill
                       at the next morning tick (at most 2 a month).
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.api.r14_status import NO_STORE, part_of, ready_of
from jarvis.api.ratelimit import RateLimiter
from jarvis.backup.tools import START, BackupDesk
from jarvis.hardening.ports import PartName
from jarvis.llm.base import ToolCall
from jarvis.logging import get_logger
from jarvis.tools.budget import turn_budget
from jarvis.tools.gateway import GatewayOutcome
from jarvis.tools.taint import context_trust

log = get_logger(__name__)

PART: PartName = "backup"
SESSION = r"^[A-Za-z0-9_-]{1,64}$"
DRILL_PER_MINUTE = 3
LIMIT_STATE = "backup_drill_limit"
OFF = "The backups part is off on this server."
NO_CONVERSATION = (
    'Open a conversation in Chat first, Sir: the approval waits there. Or say "test my backup" '
    "in the chat."
)
AWAITING = "Approve it in Approvals, Sir. The drill runs at the next morning check."
router = APIRouter(prefix="/v1/backup", dependencies=[Depends(require_auth)])


class DrillBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str | None = Field(default=None, pattern=SESSION)


def _answer(status: int, body: dict[str, Any]) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers=NO_STORE)


def _desk(request: Request) -> BackupDesk | None:
    part = part_of(request, PART)
    desk = part.services.get("backup") if part is not None else None
    return desk if isinstance(desk, BackupDesk) else None


def _limited(request: Request, uid: str) -> bool:
    limiter = getattr(request.app.state, LIMIT_STATE, None)
    if not isinstance(limiter, RateLimiter):
        limiter = RateLimiter(DRILL_PER_MINUTE)
        setattr(request.app.state, LIMIT_STATE, limiter)
    return not limiter.allow(uid)[0]


async def _his_conversation(request: Request, uid: str, session_id: str | None) -> bool:
    store = getattr(request.app.state, "store", None)
    if session_id is None or store is None:
        return False
    try:
        found = await store.get(session_id)
    except Exception as exc:  # noqa: BLE001 - unreadable: no conversation
        log.warning("backup: conversation unreadable", extra={"error": type(exc).__name__})
        return False
    return found is not None and getattr(found, "user_id", None) == uid


@router.get("", include_in_schema=False)
async def status(request: Request, uid: str = Depends(current_user)) -> JSONResponse:
    desk, ready = _desk(request), ready_of(request, PART)
    if desk is None:
        return _answer(200, {"part": PART, "ready": ready, "set_up": False, "spoken": OFF})
    return _answer(200, {"part": PART, "ready": ready, **await desk.summary()})


@router.post("/drill", include_in_schema=False)
async def drill(
    body: DrillBody, request: Request, uid: str = Depends(current_user)
) -> JSONResponse:
    if _limited(request, uid):
        return _answer(
            429, {"error": "rate_limited", "detail": "Too many requests; wait a minute."}
        )
    gateway = getattr(request.app.state, "gateway", None)
    if _desk(request) is None or gateway is None:
        return _answer(503, {"error": "unavailable", "detail": OFF})
    if not await _his_conversation(request, uid, body.session_id):
        return _answer(409, {"error": "no_conversation", "detail": NO_CONVERSATION})
    call = ToolCall(id=f"backup-{uuid.uuid4().hex[:8]}", name=START, arguments={})
    with turn_budget(), context_trust(untrusted=False, spoken=False, owner_text=None):
        res = await gateway.execute(call, scope=f"{uid}:{body.session_id}")
    if res.outcome is GatewayOutcome.AWAITING_CONFIRMATION and res.pending is not None:
        card = {"status": "awaiting", "approval_id": res.pending.id, "card": res.pending.summary}
        return _answer(202, {**card, "detail": AWAITING})
    if res.outcome is GatewayOutcome.DENIED:
        return _answer(403, {"error": "denied", "detail": "Switched off in your Permissions, Sir."})
    log.warning("backup drill card not made", extra={"outcome": res.outcome.value})
    return _answer(503, {"error": "unavailable", "detail": OFF})


__all__ = ["DRILL_PER_MINUTE", "PART", "router"]
