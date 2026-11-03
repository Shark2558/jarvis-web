# src/jarvis/api/drive.py
"""Google Drive, chosen folders (slice 12 D1; Layer 1 → 6). Owner-only: `require_auth` +
`current_user` (no client user id is read); cookie writes need `X-Requested-With: JARVIS`
(enforced by `require_auth`); ≤ CHANGES_PER_MINUTE changes a minute per owner.

GET /v1/drive              {configured: false}  — Drive is off on this server (JARVIS_DRIVE), or
                           {configured: true, service_email, folders: [{id, name, confirmed,
                           readable}], others: N, others_more, max_folders}
                           `folders`: the signed-in owner's own folders shared with JARVIS, plus
                           any switched on earlier. `readable`: whether JARVIS can read it now
                           (asked of Drive afresh; a switched-on folder that is no longer the
                           owner's share, or is in the trash, is false — and OFF for the tools).
                           `others`: how many folders other accounts shared with JARVIS (true
                           `others_more`: at least that many) — never their names or addresses
                           (that text is someone else's; the console says "not offered").
PUT /v1/drive/roots/{id}   {use: true | false} → the same view. Use on needs the owner's verified
                           Google address (a browser sign-in; the bearer token has none → 403
                           no_owner_email) and that folder, as Drive says now, to be the owner's
                           own (`jarvis.drive.live.owned_by`). Errors {error, detail}: 422 bad_id /
                           not_a_folder / validation, 403 not_offered / no_owner_email, 409
                           not_offered (not shared, or in the trash) / too_many, 404 drive_off, 429
                           rate_limited, 503 drive_unavailable / roots_unavailable (storage
                           trouble reading or changing the chosen folders), 409 switched_off (the
                           owner set the Drive permission row to Never; final review). Google's
                           own text never appears. A change is one audit entry (security review
                           SEC-3: agent "drive", outcome "changed", a hash of the folder id only).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictBool

from jarvis.api.auth import require_auth, session_email
from jarvis.api.identity import current_user
from jarvis.api.ratelimit import RateLimiter
from jarvis.api.rows import DRIVE_TOOL, is_never, switched_off_reply
from jarvis.api.settings_audit import record_change
from jarvis.config import Settings
from jarvis.drive.ports import DriveError, RootsUnreadable
from jarvis.drive.service import DriveRejected, DriveService
from jarvis.logging import get_logger

log = get_logger(__name__)

CHANGES_PER_MINUTE = 20
router = APIRouter(prefix="/v1/drive", dependencies=[Depends(require_auth)])


class UseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    use: StrictBool


class DriveOff(Exception):
    pass


def _svc(request: Request) -> DriveService | None:
    return getattr(request.app.state, "drive", None)


def _owner_email(request: Request) -> str | None:
    s: Settings = request.app.state.settings
    return session_email(request, s)


def _public(view: dict[str, Any]) -> dict[str, Any]:
    return {
        "configured": True,
        "service_email": view["service_email"],
        "folders": view["folders"],
        "others": view["others"],
        "others_more": view["others_more"],
        "max_folders": view["max_folders"],
    }


@router.get("")
async def drive_view(
    request: Request,
    svc: DriveService | None = Depends(_svc),
    uid: str = Depends(current_user),
) -> dict[str, Any]:
    if svc is None:
        return {"configured": False}
    return _public(await svc.view(uid, _owner_email(request)))


@router.put("/roots/{folder_id}", response_model=None)
async def drive_use(
    folder_id: str,
    body: UseBody,
    request: Request,
    svc: DriveService | None = Depends(_svc),
    uid: str = Depends(current_user),
) -> dict[str, Any] | JSONResponse:
    if svc is None:
        raise DriveOff()
    if await is_never(request, uid, DRIVE_TOOL):  # the console hides Drive; say so plainly
        return switched_off_reply("Google Drive")
    allowed, _ = request.app.state.drive_limit.allow(uid)
    if not allowed:
        raise DriveRejected("rate_limited", "Too many changes; wait a moment.", status=429)
    email = _owner_email(request)
    await svc.set_use(uid, email, folder_id, body.use)
    log.info("drive folder use changed", extra={"use": body.use})  # never the id or the name
    # SEC-3: the audit chain holds a hash of the folder id only
    await record_change(
        request,
        agent="drive",
        tool="drive_use",
        args={"folder": folder_id},
        detail="on" if body.use else "off",
    )
    return _public(await svc.view(uid, email))


def _err(status: int, error: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": error, "detail": detail})


def install_drive(app: FastAPI) -> None:
    """Mount /v1/drive, its per-owner change limit and its error mapping on `app`."""
    app.state.drive_limit = RateLimiter(CHANGES_PER_MINUTE)

    @app.exception_handler(DriveRejected)
    async def _rejected(_: Request, exc: DriveRejected) -> JSONResponse:
        return _err(exc.status, exc.code, str(exc))

    @app.exception_handler(DriveOff)
    async def _off(_: Request, exc: DriveOff) -> JSONResponse:
        return _err(404, "drive_off", "Google Drive isn't set up on this server.")

    @app.exception_handler(RootsUnreadable)
    async def _roots(_: Request, exc: RootsUnreadable) -> JSONResponse:
        return _err(503, "roots_unavailable", str(exc))

    @app.exception_handler(DriveError)
    async def _drive(_: Request, exc: DriveError) -> JSONResponse:
        return _err(503, "drive_unavailable", str(exc))  # our own words (DriveError contract)

    app.include_router(router)


__all__ = ["CHANGES_PER_MINUTE", "install_drive", "router"]
