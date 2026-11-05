# src/jarvis/api/vault_inbox.py
"""The DigiLocker import folder over HTTP (R2 D9; Layer 1 -> 6). Owner-only: `require_auth` +
`current_user`; cookie writes need `X-Requested-With: JARVIS`; <= 20 changes a minute per owner.

GET    /v1/vault/inbox        {available, configured, folder: {id, name} | null, offered: [{id,
                              name}], last_check_at, imported_total, waiting_review, skipped:
                              [{why, at}], note}. `available: false` (with `note`) when Drive isn't
                              set up on this server or its permission row is Never.
PUT    /v1/vault/inbox        {folder_id} -> the same view. 403 not_owner / no_owner_email, 409
                              in_use_folder / not_offered, 422 not_a_folder / bad_id.
DELETE /v1/vault/inbox        switch the import off -> the same view (nothing in Drive changes).
POST   /v1/vault/inbox/check  import now -> {imported, skipped, more, note?, stopped?}. Nothing is
                              done (no Drive call) while no folder is picked.

Errors {error, detail}; Google's text never appears. A pick, a switch-off and a check each make one
audit entry (agent "vault_inbox"; the folder id only as a hash, counts for a check).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from jarvis.api.auth import require_auth, session_email
from jarvis.api.identity import current_user
from jarvis.api.ratelimit import RateLimiter
from jarvis.api.rows import DRIVE_TOOL, is_never, switched_off_reply
from jarvis.api.settings_audit import record_change
from jarvis.config import Settings
from jarvis.drive.ports import DriveError, RootsUnreadable
from jarvis.drive.service import DriveRejected
from jarvis.logging import get_logger
from jarvis.vault_inbox.service import NOT_SET_UP, InboxService
from jarvis.vault_inbox.store import InboxUnreadable

log = get_logger(__name__)

CHANGES_PER_MINUTE = 20
router = APIRouter(prefix="/v1/vault/inbox", dependencies=[Depends(require_auth)])
SWITCHED_OFF_NOTE = "Drive is switched off in Permissions (Never), so nothing is imported."


class PickBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    folder_id: str


def _svc(request: Request) -> InboxService | None:
    return getattr(request.app.state, "vault_inbox", None)


def _email(request: Request) -> str | None:
    s: Settings = request.app.state.settings
    return session_email(request, s)


def _off(note: str) -> dict[str, Any]:
    return {
        "available": False,
        "configured": False,
        "folder": None,
        "offered": [],
        "last_check_at": None,
        "imported_total": 0,
        "waiting_review": 0,
        "skipped": [],
        "note": note,
    }


def _err(status: int, error: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": error, "detail": detail})


def _limited(request: Request, uid: str) -> JSONResponse | None:
    allowed, _ = request.app.state.vault_inbox_limit.allow(uid)
    return None if allowed else _err(429, "rate_limited", "Too many changes; wait a moment.")


@router.get("")
async def inbox_view(
    request: Request,
    svc: InboxService | None = Depends(_svc),
    uid: str = Depends(current_user),
) -> dict[str, Any]:
    if svc is None:
        return _off(NOT_SET_UP)
    if await is_never(request, uid, DRIVE_TOOL):
        return _off(SWITCHED_OFF_NOTE)
    return await svc.view(uid, _email(request))


@router.put("", response_model=None)
async def inbox_pick(
    body: PickBody,
    request: Request,
    svc: InboxService | None = Depends(_svc),
    uid: str = Depends(current_user),
) -> dict[str, Any] | JSONResponse:
    if svc is None:
        return _err(404, "drive_off", NOT_SET_UP)
    if await is_never(request, uid, DRIVE_TOOL):
        return switched_off_reply("Google Drive")
    if (limited := _limited(request, uid)) is not None:
        return limited
    await svc.pick(uid, _email(request), body.folder_id)
    log.info("vault inbox picked")  # never the id or the name
    await record_change(
        request,
        agent="vault_inbox",
        tool="vault_inbox_pick",
        args={"folder": body.folder_id},
        detail="on",
    )
    return await svc.view(uid, _email(request))


@router.delete("", response_model=None)
async def inbox_clear(
    request: Request,
    svc: InboxService | None = Depends(_svc),
    uid: str = Depends(current_user),
) -> dict[str, Any] | JSONResponse:
    if svc is None:
        return _err(404, "drive_off", NOT_SET_UP)
    if (limited := _limited(request, uid)) is not None:
        return limited
    await svc.clear(uid)
    await record_change(
        request, agent="vault_inbox", tool="vault_inbox_clear", args={}, detail="off"
    )
    return await svc.view(uid, _email(request))


@router.post("/check", response_model=None)
async def inbox_check(
    request: Request,
    svc: InboxService | None = Depends(_svc),
    uid: str = Depends(current_user),
) -> dict[str, Any] | JSONResponse:
    if svc is None:
        return _err(404, "drive_off", NOT_SET_UP)
    if await is_never(request, uid, DRIVE_TOOL):
        return switched_off_reply("Google Drive")
    if (limited := _limited(request, uid)) is not None:
        return limited
    result = await svc.check(uid)
    await record_change(
        request,
        agent="vault_inbox",
        tool="vault_inbox_check",
        args={"imported": result.imported, "skipped": result.skipped},
        detail="checked",
    )
    return result.public()


def install_vault_inbox(app: FastAPI) -> None:
    """Mount /v1/vault/inbox, its per-owner change limit and its error mapping on `app`. The
    service is `app.state.vault_inbox` (None: the routes say Drive isn't set up)."""
    app.state.vault_inbox_limit = RateLimiter(CHANGES_PER_MINUTE)

    @app.exception_handler(DriveRejected)
    async def _rejected(_: Request, exc: DriveRejected) -> JSONResponse:
        return _err(exc.status, exc.code, str(exc))

    @app.exception_handler(InboxUnreadable)
    async def _unreadable(_: Request, exc: InboxUnreadable) -> JSONResponse:
        return _err(503, "inbox_unavailable", str(exc))

    @app.exception_handler(RootsUnreadable)
    async def _roots(_: Request, exc: RootsUnreadable) -> JSONResponse:
        return _err(503, "roots_unavailable", str(exc))

    @app.exception_handler(DriveError)
    async def _drive(_: Request, exc: DriveError) -> JSONResponse:
        return _err(503, "drive_unavailable", str(exc))

    app.include_router(router)


__all__ = ["CHANGES_PER_MINUTE", "install_vault_inbox", "router"]
