# src/jarvis/api/vault.py
"""The document vault's HTTP surface (R2 D1-D8; Layer 1 -> 7). Owner-only: `require_auth` +
`current_user` (no client user id is read); cookie writes need `X-Requested-With: JARVIS`. Errors
are `{error, detail, reason?}` in plain words.

GET    /v1/vault                       {available, reason?, items, holders, totals, settings,
                                        unlock: {required: passkey|sign_in|none, console}}
POST   /v1/vault/upload[?item=&type=&holder=]  raw body <= 10 MB -> 201 {item, proposal, duplicate}
PATCH  /v1/vault/items/{id}            {type?, holder_id?, title?, last4?, note?, issued_on?,
                                        expires_on?, reminders?, confirm?} -> ItemView
DELETE /v1/vault/items/{id}            -> {undo_id} (Recently deleted, 30 days)
POST   /v1/vault/holders {label} | DELETE /v1/vault/holders/{id}
PUT    /v1/vault/settings              {alert_detail?, brief?, inbox_copy?}
POST   /v1/vault/unlock {proof?}       -> {token, until, minutes}; 403 console_only /
                                        passkey_required / passkey_rejected / reauth_required
DELETE /v1/vault/unlock                forget this owner's unlock tokens
POST   /v1/vault/items/{id}/files/{fid}/ticket | POST /v1/vault/export/ticket
                                        header X-Jarvis-Vault -> {ticket, expires_in_s: 60}
GET    /v1/vault/download/{ticket}     the file or a ZIP; 410 used / expired

Opening files is the console only: a bearer-token caller (CLI, scripts) is refused with 403
`console_only` for unlock, tickets and downloads. Every unlock, open and export is audited (agent
`owner`, ids and counts only) BEFORE the first byte; if the audit can't be written, nothing is sent.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr

from jarvis.api.auth import fresh_sign_in_left, require_auth, session_email
from jarvis.api.body import read_capped
from jarvis.api.identity import current_user
from jarvis.api.ratelimit import RateLimiter
from jarvis.api.settings_audit import record_change
from jarvis.config import AuthMode
from jarvis.core.guardrails import ActionRisk
from jarvis.logging import get_logger
from jarvis.permissions.errors import (
    PasskeyDataUnreadable,
    PasskeyRejected,
    PasskeyRequired,
    ProofRequired,
)
from jarvis.permissions.models import PasskeyProof
from jarvis.vault.models import ID_FILE, ID_HOLDER, ID_ITEM, VaultRejected, VaultUnavailable
from jarvis.vault.ports import MAX_FILE_BYTES
from jarvis.vault.service import VaultService
from jarvis.vault.unlock import EXPORT, TicketGone, UnlockStore

log = get_logger(__name__)

VAULT_UPLOAD_PATH = "/v1/vault/upload"
VAULT_BODY_BYTES = MAX_FILE_BYTES + 64 * 1024
UPLOADS_PER_MINUTE = 6
CHANGES_PER_MINUTE = 30
UNLOCKS_PER_MINUTE = 10
OPENS_PER_MINUTE = 20
READ_TIMEOUT_S = 60.0
PANEL_CHECK_S = 5.0
TOKEN_HEADER = "X-Jarvis-Vault"
NO_KEY = "Not available on this server (no encryption key)."
LOCKED = "Unlock the vault first."
router = APIRouter(prefix="/v1/vault", dependencies=[Depends(require_auth)])


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ItemPatchBody(_In):
    type: StrictStr | None = None
    holder_id: StrictStr | None = None
    title: StrictStr | None = None
    last4: StrictStr | None = None
    note: StrictStr | None = None
    issued_on: StrictStr | None = None
    expires_on: StrictStr | None = None
    reminders: list[StrictInt] | None = None
    confirm: StrictBool = False


class HolderBody(_In):
    label: StrictStr


class SettingsBody(_In):
    alert_detail: StrictStr | None = None
    brief: StrictBool | None = None
    inbox_copy: StrictBool | None = None


class UnlockBody(_In):
    proof: PasskeyProof | None = None


def _err(status: int, error: str, detail: str, **extra: Any) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": error, "detail": detail, **extra})


def _svc(request: Request) -> VaultService:
    svc: VaultService | None = getattr(request.app.state, "vault", None)
    if svc is None:
        raise VaultRejected("vault_off", NO_KEY, status=503)
    return svc


def _unlocks(request: Request) -> UnlockStore:
    store: UnlockStore | None = getattr(request.app.state, "vault_unlock", None)
    if store is None:
        raise VaultRejected("vault_off", NO_KEY, status=503)
    return store


def _limit(request: Request, name: str, uid: str) -> None:
    allowed, wait = request.app.state.vault_limits[name].allow(uid)
    if not allowed:
        raise VaultRejected("rate_limited", "Too many requests; wait a moment.", status=429)


def _console_only(request: Request) -> None:
    """Files open in the console only: a signed-in browser (or token-mode dev)."""
    s = request.app.state.settings
    if session_email(request, s) is not None:
        return
    if s.auth_mode is AuthMode.TOKEN and s.env == "dev":
        return
    raise VaultRejected(
        "console_only", "Documents open only in the JARVIS console, not from a script.", status=403
    )


async def _passkeys_in_force(request: Request, uid: str) -> bool:
    perms = getattr(request.app.state, "permissions", None)
    return bool(perms is not None and await perms.passkey_required(uid))


async def _audit(request: Request, tool: str, args: dict[str, Any], detail: str = "") -> bool:
    """Audit first; False means the entry could not be written (the caller sends nothing)."""
    gw = getattr(request.app.state, "gateway", None)
    if gw is None:
        log.warning("no audit chain for a vault event", extra={"tool": tool})
        return True
    try:
        await gw.audit.append(
            agent="owner",
            tool=tool,
            risk=ActionRisk.READ_ONLY,
            outcome="executed",
            args=args,
            detail=detail,
        )
    except Exception as exc:  # noqa: BLE001
        log.error(
            "AUDIT WRITE FAILED for a vault event",
            extra={"tool": tool, "error": type(exc).__name__},
        )
        return False
    return True


# ---- reading ------------------------------------------------------------------------------


@router.get("")
async def vault_view(request: Request, uid: str = Depends(current_user)) -> Any:
    svc: VaultService | None = getattr(request.app.state, "vault", None)
    if svc is None:
        return {"available": False, "reason": NO_KEY, "items": [], "holders": []}
    reminders = getattr(request.app.state, "vault_reminders", None)
    if reminders is not None:  # the panel opening is a chance to send today's reminders
        try:
            await asyncio.wait_for(reminders.check(uid), PANEL_CHECK_S)
        except Exception as exc:  # noqa: BLE001
            log.warning("vault reminder check skipped", extra={"error": type(exc).__name__})
    view = await svc.view(uid)
    s = request.app.state.settings
    if await _passkeys_in_force(request, uid):
        required = "passkey"
    else:
        required = "sign_in" if s.auth_mode is AuthMode.GOOGLE else "none"
    console = session_email(request, s) is not None or (
        s.auth_mode is AuthMode.TOKEN and s.env == "dev"
    )
    return {**view, "unlock": {"required": required, "console": console}}


# ---- adding and changing --------------------------------------------------------------------


@router.post("/upload", status_code=201, response_model=None)
async def upload(
    request: Request,
    item: str | None = Query(default=None, max_length=40),
    type: str | None = Query(default=None, max_length=40),  # noqa: A002
    holder: str | None = Query(default=None, max_length=40),
    uid: str = Depends(current_user),
) -> Any:
    svc = _svc(request)
    _limit(request, "upload", uid)
    if holder is not None and holder != "me" and not ID_HOLDER.fullmatch(holder):
        raise VaultRejected("invalid", "That family member isn't in your vault list.")

    def too_large() -> Exception:
        return VaultRejected("too_large", "Files can be up to 10 MB.", status=413)

    try:
        data = await asyncio.wait_for(
            read_capped(request, MAX_FILE_BYTES, too_large=too_large), READ_TIMEOUT_S
        )
    except TimeoutError:
        raise VaultRejected(
            "upload_timeout",
            "The upload took too long. Check the connection and try again.",
            status=408,
        ) from None
    added = await svc.add_file(uid, data, item_id=item, type_hint=type, holder_id=holder)
    view = svc.item_view(await svc.index(uid), added.item, svc.today())
    if not added.duplicate:
        await record_change(
            request, agent="vault", tool="vault_file_add", args={"item": added.item.id}
        )
    body = {"item": view, "proposal": view["proposal"], "duplicate": added.duplicate}
    return JSONResponse(status_code=200 if added.duplicate else 201, content=body)


@router.patch("/items/{item_id}")
async def item_patch(
    item_id: str, body: ItemPatchBody, request: Request, uid: str = Depends(current_user)
) -> Any:
    svc = _svc(request)
    _limit(request, "change", uid)
    return await svc.update(uid, item_id, body.model_dump(exclude_unset=True))


@router.delete("/items/{item_id}")
async def item_delete(item_id: str, request: Request, uid: str = Depends(current_user)) -> Any:
    svc = _svc(request)
    _limit(request, "change", uid)
    undo_id = await svc.remove(uid, item_id)
    await record_change(request, agent="vault", tool="vault_item_remove", args={"item": item_id})
    return {"undo_id": undo_id, "kind": "vault_item"}


@router.post("/holders", status_code=201)
async def holder_add(body: HolderBody, request: Request, uid: str = Depends(current_user)) -> Any:
    svc = _svc(request)
    _limit(request, "change", uid)
    return (await svc.add_holder(uid, body.label)).model_dump()


@router.delete("/holders/{holder_id}")
async def holder_remove(holder_id: str, request: Request, uid: str = Depends(current_user)) -> Any:
    svc = _svc(request)
    _limit(request, "change", uid)
    if not ID_HOLDER.fullmatch(holder_id):
        raise VaultRejected("not_found", "That family member isn't in the list.", status=404)
    await svc.remove_holder(uid, holder_id)
    return {"removed": holder_id}


@router.put("/settings")
async def settings_put(
    body: SettingsBody, request: Request, uid: str = Depends(current_user)
) -> Any:
    svc = _svc(request)
    _limit(request, "change", uid)
    return await svc.update_settings(uid, body.model_dump(exclude_none=True))


# ---- unlock, tickets, download ----------------------------------------------------------------


def _proof_failure(exc: Exception) -> JSONResponse:
    if isinstance(exc, PasskeyRequired):
        return _err(403, "passkey_required", str(exc))
    if isinstance(exc, PasskeyRejected):
        return _err(403, "passkey_rejected", str(exc), reason=exc.reason)
    if isinstance(exc, ProofRequired):
        return _err(403, "proof_required", str(exc), reason=exc.reason)
    return _err(503, "passkeys_unreadable", "Your passkeys can't be read right now.")


@router.post("/unlock", response_model=None)
async def unlock(body: UnlockBody, request: Request, uid: str = Depends(current_user)) -> Any:
    store = _unlocks(request)
    _svc(request)
    _console_only(request)
    _limit(request, "unlock", uid)
    s = request.app.state.settings
    perms = getattr(request.app.state, "permissions", None)
    how: str | None = None
    if perms is not None:
        try:
            how = await perms.check_purpose(uid, "vault_unlock", None, body.proof)
        except (PasskeyRequired, PasskeyRejected, ProofRequired, PasskeyDataUnreadable) as exc:
            await _audit(request, "vault_unlock", {"result": "refused"}, type(exc).__name__)
            return _proof_failure(exc)
    if how is None and s.auth_mode is AuthMode.GOOGLE and not fresh_sign_in_left(request, s):
        return _err(
            403, "reauth_required", "Sign in with Google again to open your vault.", reason="reauth"
        )
    if not await _audit(request, "vault_unlock", {"result": "granted"}, how or "sign-in"):
        raise VaultUnavailable("the unlock could not be recorded")
    grant = await store.grant(uid)
    return {"token": grant.token, "until": grant.until.isoformat(), "minutes": store.minutes}


@router.delete("/unlock")
async def lock(request: Request, uid: str = Depends(current_user)) -> Any:
    await _unlocks(request).lock(uid)
    return {"locked": True}


async def _ticket(request: Request, uid: str, token: str | None, item: str | None, fid: str) -> Any:
    store = _unlocks(request)
    _console_only(request)
    _limit(request, "open", uid)
    try:
        t = await store.ticket(uid, token or "", item, fid)
    except PermissionError:
        return _err(403, "locked", LOCKED, reason="locked")
    return {"ticket": t.ticket, "expires_in_s": t.expires_in_s}


@router.post("/items/{item_id}/files/{fid}/ticket", response_model=None)
async def file_ticket(
    item_id: str,
    fid: str,
    request: Request,
    uid: str = Depends(current_user),
    token: str | None = Header(default=None, alias=TOKEN_HEADER),
) -> Any:
    svc = _svc(request)
    item = await svc.get_item(uid, item_id) if ID_ITEM.fullmatch(item_id) else None
    if item is None or not ID_FILE.fullmatch(fid) or not any(f.fid == fid for f in item.files):
        raise VaultRejected("not_found", "That file isn't in your vault.", status=404)
    return await _ticket(request, uid, token, item_id, fid)


@router.post("/export/ticket", response_model=None)
async def export_ticket(
    request: Request,
    uid: str = Depends(current_user),
    token: str | None = Header(default=None, alias=TOKEN_HEADER),
) -> Any:
    _svc(request)
    return await _ticket(request, uid, token, None, EXPORT)


_TICKET = re.compile(r"[A-Za-z0-9_\-]{20,100}")


@router.get("/download/{ticket}", response_model=None)
async def download(ticket: str, request: Request, uid: str = Depends(current_user)) -> Any:
    svc = _svc(request)
    store = _unlocks(request)
    _console_only(request)
    gone = _err(410, "gone", "That download link was already used or has expired. Open it again.")
    if not _TICKET.fullmatch(ticket):
        return gone
    try:
        taken = await store.take(uid, ticket)
    except TicketGone:
        return gone
    if taken.fid == EXPORT:
        out = await svc.stream_export(uid)
        recorded = await _audit(request, "vault_export", {"files": out.files})
    else:
        out = await svc.stream_file(uid, taken.item or "", taken.fid)
        recorded = await _audit(request, "vault_open", {"item": taken.item, "file": taken.fid})
    if not recorded:  # nothing is sent unless the audit entry exists
        raise VaultUnavailable("the download could not be recorded")
    headers = {
        "Content-Disposition": f'attachment; filename="{out.filename}"',
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if out.size is not None:
        headers["Content-Length"] = str(out.size)
    return StreamingResponse(out.body, media_type=out.mime, headers=headers)


def install_vault(app: FastAPI) -> None:
    """Mount /v1/vault, its per-owner limits and its error mapping on `app`. The service is
    `app.state.vault` (None: the vault is off), the unlock store `app.state.vault_unlock`, and
    the optional reminder job `app.state.vault_reminders` (checked when the panel opens)."""
    app.state.vault_limits = {
        "upload": RateLimiter(UPLOADS_PER_MINUTE),
        "change": RateLimiter(CHANGES_PER_MINUTE),
        "unlock": RateLimiter(UNLOCKS_PER_MINUTE),
        "open": RateLimiter(OPENS_PER_MINUTE),
    }

    @app.exception_handler(VaultRejected)
    async def _rejected(_: Request, exc: VaultRejected) -> JSONResponse:
        return _err(exc.status, exc.code, exc.detail)

    @app.exception_handler(VaultUnavailable)
    async def _unavailable(_: Request, exc: VaultUnavailable) -> JSONResponse:
        return _err(503, "unavailable", "The vault isn't available right now. Nothing was changed.")

    app.include_router(router)


__all__ = [
    "VAULT_BODY_BYTES",
    "VAULT_UPLOAD_PATH",
    "install_vault",
    "router",
]
