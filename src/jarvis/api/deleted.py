# src/jarvis/api/deleted.py
"""Recently deleted over HTTP (slice 11 D1; Layer 1 → 3). Owner-only like approvals:
`require_auth` + `current_user` (no client user id is read), cookie writes need
`X-Requested-With: JARVIS`, rate-limited with the rest of /v1. Without the bin — i.e. without
persistent storage, where every delete stays R3 — the list says `available: false` and the
writes are 404.

GET    /v1/deleted               DeletedList {items: [{id, kind, title, deleted_at, expires_at,
                                 restored}], kept_days, available}: what can still be restored,
                                 newest first.
                                 Titles are plain text (the console renders them with
                                 textContent); the model only ever sees them fenced.
POST   /v1/deleted/{id}/restore  RestoreOutcome {status: restored | already_restored, message,
                                 undo_id, kind, title, new_id, note}. The owner's own click, like
                                 approving a card: it is audited (agent "console").
                                 404 not_found (unknown / malformed id), 410 expired, 409 busy (a
                                 restore is under way) or still_there (never deleted: no copy
                                 made), 503 unavailable (Google not linked), 502 restore_failed.
DELETE /v1/deleted/{id}          "Remove now": the copy goes at once (it can't be restored after).
                                 {removed: true, id}; 404 not_found. Audited (agent "console").

Error text: only our own error classes carry their words to the owner (Google errors are already
vendor-free plain words); anything else is one generic sentence, never a stack trace.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from jarvis.api.auth import require_auth
from jarvis.api.identity import current_user
from jarvis.core.guardrails import ActionRisk
from jarvis.integrations.google import GoogleAPIError, GoogleNotConnected
from jarvis.logging import get_logger
from jarvis.tools.tasks_api import TasksNotGranted
from jarvis.undo.models import UNDO_ID, DeletedList, DeletedView, RestoreOutcome, RestoreStatus
from jarvis.undo.service import UndoBin

router = APIRouter(prefix="/v1/deleted", dependencies=[Depends(require_auth)])
log = get_logger(__name__)

RESTORE_FAILED = "Couldn't restore it just now. Try again in a moment."
NOT_AVAILABLE = "Recently deleted is not available on this server."
NOT_FOUND = "That isn't in Recently deleted (it may have been cleared already)."
_ERRORS: dict[RestoreStatus, tuple[int, str]] = {
    RestoreStatus.UNKNOWN: (404, "not_found"),
    RestoreStatus.EXPIRED: (410, "expired"),
    RestoreStatus.BUSY: (409, "busy"),
    RestoreStatus.STILL_THERE: (409, "still_there"),
    RestoreStatus.UNAVAILABLE: (503, "unavailable"),
}


def _bin(request: Request) -> UndoBin:
    undo: UndoBin | None = getattr(request.app.state, "undo", None)
    if undo is None:
        raise LookupError(NOT_AVAILABLE)
    return undo


def _err(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "detail": detail})


async def _audit(request: Request, tool: str, undo_id: str, outcome: str, detail: str) -> None:
    """It already happened (or failed): an audit outage is logged, never raised."""
    gw = getattr(request.app.state, "gateway", None)
    if gw is None:
        return
    try:
        await gw.audit.append(
            agent="console",
            tool=tool,
            risk=ActionRisk.REVERSIBLE,
            outcome=outcome,
            args={"undo_id": undo_id},
            detail=detail,
        )
    except Exception as exc:  # noqa: BLE001
        log.error("AUDIT WRITE FAILED for Recently deleted", extra={"error": type(exc).__name__})


@router.get("", response_model=DeletedList)
async def list_deleted(request: Request, uid: str = Depends(current_user)) -> DeletedList:
    undo: UndoBin | None = getattr(request.app.state, "undo", None)
    if undo is None:  # no persistent storage: nothing is kept (the console says so, no 404)
        return DeletedList(items=[], available=False)
    return DeletedList(items=[DeletedView.of(i) for i in await undo.recent(uid)])


async def _restore(
    request: Request, undo: UndoBin, uid: str, undo_id: str
) -> RestoreOutcome | JSONResponse:
    try:
        return await undo.restore(uid, undo_id)
    except (GoogleNotConnected, TasksNotGranted) as exc:  # plain words already
        await _audit(request, "deleted_restore", undo_id, "error", type(exc).__name__)
        return _err(503, "unavailable", str(exc))
    except GoogleAPIError as exc:  # our own words, vendor text never in them
        await _audit(request, "deleted_restore", undo_id, "error", type(exc).__name__)
        return _err(502, "restore_failed", str(exc) or RESTORE_FAILED)
    except Exception as exc:  # noqa: BLE001 — never a stack trace or someone else's text
        log.error("restore failed", extra={"error": type(exc).__name__})
        await _audit(request, "deleted_restore", undo_id, "error", type(exc).__name__)
        return _err(502, "restore_failed", RESTORE_FAILED)


@router.post("/{undo_id}/restore", response_model=RestoreOutcome)
async def restore(
    undo_id: str, request: Request, uid: str = Depends(current_user)
) -> RestoreOutcome | JSONResponse:
    out = await _restore(request, _bin(request), uid, undo_id)  # no bin: 404 "not available"
    if isinstance(out, JSONResponse):
        return out
    if out.status in _ERRORS:
        status, code = _ERRORS[out.status]
        return _err(status, code, out.message)
    if out.status is RestoreStatus.RESTORED:
        await _audit(request, "deleted_restore", undo_id, "executed", "owner: Restore")
    return out


class Removed(BaseModel):
    removed: bool
    id: str


@router.delete("/{undo_id}", response_model=Removed)
async def purge(
    undo_id: str, request: Request, uid: str = Depends(current_user)
) -> Removed | JSONResponse:
    undo = _bin(request)
    if not UNDO_ID.fullmatch(undo_id) or not await undo.purge(uid, undo_id):
        return _err(404, "not_found", NOT_FOUND)
    await _audit(request, "deleted_purge", undo_id, "executed", "owner: Remove now")
    return Removed(removed=True, id=undo_id)


__all__ = ["router"]
