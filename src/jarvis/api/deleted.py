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
                                 404 not_found (unknown / malformed id; or, R2, the item was
                                 removed for good: "It's gone", the entry is dropped), 410
                                 expired, 409 busy (a restore is under way) or still_there (never
                                 deleted: no copy made), 503 unavailable (Google not linked; R2:
                                 that feature is off here), 502 restore_failed.
DELETE /v1/deleted/{id}          "Remove now": the copy goes at once (it can't be restored after).
                                 {removed: true, id}; 404 not_found. Audited (agent "console").
                                 R2 I1: for a vault document, a note or a thing
                                 (`PASSKEY_PURGE_KINDS`, nothing brings them back) the optional
                                 body {proof} must be a passkey check for purpose privacy_delete
                                 made for exactly this bin id; with no passkeys in force, a Google
                                 sign-in under 5 minutes old (token-mode dev: none). 403
                                 passkey_required / passkey_rejected / proof_required {reason:
                                 reauth}, 503 passkeys_unreadable. A restored entry is 404 and
                                 asks for nothing.

Error text: only our own error classes carry their words to the owner (Google errors are already
vendor-free plain words); anything else is one generic sentence, never a stack trace.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from jarvis.api.auth import fresh_sign_in_left, require_auth
from jarvis.api.identity import current_user
from jarvis.config import AuthMode
from jarvis.core.guardrails import ActionRisk
from jarvis.integrations.google import GoogleAPIError, GoogleNotConnected
from jarvis.logging import get_logger
from jarvis.permissions.errors import (
    PasskeyDataUnreadable,
    PasskeyRejected,
    PasskeyRequired,
    ProofRequired,
)
from jarvis.permissions.models import PasskeyProof
from jarvis.tools.tasks_api import TasksNotGranted
from jarvis.undo.models import (
    PASSKEY_PURGE_KINDS,
    UNDO_ID,
    DeletedItem,
    DeletedList,
    DeletedView,
    RestoreOutcome,
    RestoreStatus,
)
from jarvis.undo.service import MSG_GONE, Gone, PurgeFailed, UndoBin

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
    except Gone as exc:  # R2 review H2: removed for good (the bin dropped its entry)
        await _audit(request, "deleted_restore", undo_id, "error", type(exc).__name__)
        return _err(404, "not_found", MSG_GONE)
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
        activity = getattr(request.app.state, "activity", None)
        if activity is not None:  # R1 B: a "You restored ..." row in Activity (never raises)
            await activity.record_restore(uid, out, session_id=None)
    return out


class Removed(BaseModel):
    removed: bool
    id: str


class RemoveBody(BaseModel):
    """R2: the passkey check for a kind nothing can bring back (absent for the others)."""

    model_config = ConfigDict(extra="forbid")
    proof: PasskeyProof | None = None


REAUTH = "Sign in with Google again (within 5 minutes) to remove it for good."


def _err_reason(status: int, code: str, detail: str, reason: str) -> JSONResponse:
    body = {"error": code, "detail": detail, "reason": reason}
    return JSONResponse(status_code=status, content=body)


def _proof_failure(exc: Exception) -> JSONResponse:
    if isinstance(exc, PasskeyRequired):
        return _err(403, "passkey_required", str(exc))
    if isinstance(exc, PasskeyRejected):
        return _err_reason(403, "passkey_rejected", str(exc), exc.reason)
    if isinstance(exc, ProofRequired):
        return _err_reason(403, "proof_required", str(exc), exc.reason)
    return _err(503, "passkeys_unreadable", "Your passkeys can't be read right now.")


async def _for_good(
    request: Request, uid: str, item: DeletedItem, proof: PasskeyProof | None
) -> str | JSONResponse:
    """R2 D8: a vault document, note or thing goes for good only on a passkey check made for this
    bin id (purpose privacy_delete) or, with no passkeys in force, a recent Google sign-in.
    Returns the audit note, or the refusal. Fails closed."""
    perms = getattr(request.app.state, "permissions", None)
    how: str | None = None
    if perms is not None:
        try:
            how = await perms.check_purpose(uid, "privacy_delete", item.id, proof)
        except (PasskeyRequired, PasskeyRejected, ProofRequired, PasskeyDataUnreadable) as exc:
            await _audit(request, "deleted_purge", item.id, "denied", type(exc).__name__)
            return _proof_failure(exc)
    if how is not None:
        return how
    s = request.app.state.settings
    if s.auth_mode is AuthMode.GOOGLE and not fresh_sign_in_left(request, s):
        return _err_reason(403, "proof_required", REAUTH, "reauth")
    return "sign-in" if s.auth_mode is AuthMode.GOOGLE else "no passkeys"


@router.delete("/{undo_id}", response_model=Removed)
async def purge(
    undo_id: str,
    request: Request,
    uid: str = Depends(current_user),
    body: RemoveBody | None = Body(default=None),  # noqa: B008 - FastAPI's way
) -> Removed | JSONResponse:
    undo = _bin(request)
    item = await undo.get(uid, undo_id) if UNDO_ID.fullmatch(undo_id) else None
    if item is None or item.restored:  # never a proof for something that can't be purged
        return _err(404, "not_found", NOT_FOUND)
    how = "owner: Remove now"
    if item.kind in PASSKEY_PURGE_KINDS:
        checked = await _for_good(request, uid, item, body.proof if body else None)
        if isinstance(checked, JSONResponse):
            return checked
        how += f"; {checked}"
    try:
        purged = await undo.purge(uid, undo_id)
    except PurgeFailed as exc:  # R2: the kind's purger failed; the entry stays (plain words)
        return _err(503, "unavailable", str(exc))
    if not purged:
        return _err(404, "not_found", NOT_FOUND)
    await _audit(request, "deleted_purge", undo_id, "executed", how)
    return Removed(removed=True, id=undo_id)


__all__ = ["router"]
