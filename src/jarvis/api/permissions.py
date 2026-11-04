# src/jarvis/api/permissions.py
"""Owner permissions and passkeys over HTTP (slice 10 D; Layer 1 → 4). Owner-only: `require_auth`
+ `current_user` (no client user id is read); cookie writes need `X-Requested-With: JARVIS`.

GET  /v1/permissions                   PermissionsView: groups [{id, section, label, hint,
                                       irreversible, choices, effect, default}], require_passkey,
                                       passkeys [{id, label, created_at, last_used_at, backed_up,
                                       via_recovery}], passkeys_available, passkeys_note,
                                       passkeys_error, reset {requested_at, effective_at} | null,
                                       can_reauth, fresh_sign_in_s, max_passkeys, label_max, rev
PUT  /v1/permissions                   {groups?: {id: allow|ask|deny}, require_passkey?, proof?}
                                       422 input_rejected (Allow on an irreversible group, unknown
                                       group / effect, requirement on without a passkey);
                                       403 proof_required when switching the requirement off
POST /v1/passkeys/challenge            {purpose: approve|remove|add|disable|cancel_reset,
                                       approval_id?, credential_id?} → {challenge_id, public_key,
                                       expires_in_s} (credentials.get options; 2 min, single use)
POST /v1/passkeys/register/options     {proof?} → creation options. The first passkey: a browser
                                       signed in with Google again < 5 min ago (bearer: refused);
                                       later ones: a passkey check for "add"
POST /v1/passkeys/register             {challenge_id, credential, label} → PermissionsView
POST /v1/passkeys/{id}/remove          {proof} → PermissionsView (a check for exactly this one)
POST /v1/passkeys/reset                start removing ALL passkeys in 24 h (a browser signed in
                                       with Google again < 5 min ago; inbox notice; audit)
POST /v1/passkeys/reset/cancel         {proof} → cancel it with any passkey

Approving an irreversible card while the requirement is in force: POST /v1/approvals/{id}/approve
{session_id, passkey: {challenge_id, credential}}; the gateway's approval guard checks it on the
card as it is at that moment. Without it: 403 passkey_required — what the CLI and scripts get.

Errors: {error, detail, reason?}: 409 passkeys_unavailable, 403 passkey_required, 403
proof_required {reason: reauth|passkey}, 403 passkey_rejected {reason: replayed|expired|
wrong_action|unknown_passkey|unreadable|failed}, 503 passkeys_unreadable, 404 not_found, 429.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from jarvis.api.auth import fresh_sign_in_left, require_auth, session_email
from jarvis.api.identity import current_user
from jarvis.api.ratelimit import RateLimiter
from jarvis.config import AuthMode, Settings
from jarvis.core.models import PendingApproval
from jarvis.integrations.google import GoogleConnector
from jarvis.logging import get_logger
from jarvis.permissions.availability import notes as availability_notes
from jarvis.permissions.ceremony import RelyingParty
from jarvis.permissions.errors import (
    PasskeyDataUnreadable,
    PasskeyRejected,
    PasskeyRequired,
    PasskeysUnavailable,
    PermissionRejected,
    ProofRequired,
)
from jarvis.permissions.models import (
    CancelResetRequest,
    ChallengeRequest,
    ChallengeView,
    PermissionsPatch,
    PermissionsView,
    RegisterOptionsRequest,
    RegisterRequest,
    RemoveRequest,
)
from jarvis.permissions.notify import inbox_notifier
from jarvis.permissions.passkeys import ChallengeStore, PasskeyStore
from jarvis.permissions.service import UNREADABLE, PermissionsService
from jarvis.permissions.store import PermissionsStore
from jarvis.storage.docs import Docs
from jarvis.tools.audit import AuditTrail

router = APIRouter(dependencies=[Depends(require_auth)])
log = get_logger(__name__)

VIEW_PER_MINUTE = 60
CHANGE_PER_MINUTE = 30
CEREMONY_PER_MINUTE = 20
OWNER_NAME = "JARVIS owner"


class PermissionsRateLimited(Exception):
    def __init__(self, wait_s: float) -> None:
        self.retry_after = max(1, int(wait_s + 0.999))
        super().__init__("too many requests")


def build_permissions(
    s: Settings,
    docs: Docs,
    *,
    audit: AuditTrail | None = None,
    google: GoogleConnector | None = None,
) -> PermissionsService:
    """Choices, passkeys and challenges on the app's documents (Firestore in production); every
    change goes to the same audit chain as the tool calls; a reset notice to the Gmail inbox."""
    p = s.firestore_prefix
    return PermissionsService(
        store=PermissionsStore(docs, prefix=p),
        passkeys=PasskeyStore(docs, prefix=p),
        challenges=ChallengeStore(docs, prefix=p),
        rp=RelyingParty.from_base_url(s.public_base_url),
        can_reauth=s.auth_mode is AuthMode.GOOGLE,
        audit=audit,
        notify=inbox_notifier(google),
    )


def _svc(request: Request) -> PermissionsService:
    svc: PermissionsService | None = getattr(request.app.state, "permissions", None)
    if svc is None:
        raise LookupError("Permissions are not available on this server.")
    return svc


def _limit(request: Request, name: str, uid: str) -> None:
    allowed, wait = request.app.state.permission_limits[name].allow(uid)
    if not allowed:
        raise PermissionsRateLimited(wait)


def _fresh(request: Request) -> int | None:
    """Seconds left of a Google re-sign-in in THIS browser; None for a bearer caller."""
    return fresh_sign_in_left(request, request.app.state.settings)


async def _lookup(request: Request, approval_id: str) -> Any:
    gw = getattr(request.app.state.brain, "gateway", None)
    return await gw.gate.get(approval_id) if gw is not None else None


async def _noted(request: Request, uid: str, view: PermissionsView) -> PermissionsView:
    """R1 D9: every group keeps its row; `available` / `note` say what is not connected yet.
    Only GET /v1/permissions computes them (one Google status read per load); the console keeps
    the notes it has when a change answers with the plain view.
    Fail-soft: if the check fails, every row stays listed as available with no note."""
    try:
        found = await availability_notes(request.app.state, uid)
    except Exception as exc:  # noqa: BLE001
        log.warning("availability notes failed", extra={"error": type(exc).__name__})
        return view
    groups = [
        g.model_copy(update={"available": a.available, "note": a.note})
        if (a := found.get(g.id)) is not None
        else g
        for g in view.groups
    ]
    return view.model_copy(update={"groups": groups})


@router.get("/v1/permissions", response_model=PermissionsView)
async def get_permissions(
    request: Request, svc: PermissionsService = Depends(_svc), uid: str = Depends(current_user)
) -> PermissionsView:
    _limit(request, "view", uid)
    return await _noted(request, uid, await svc.view(uid, fresh_left_s=_fresh(request)))


@router.put("/v1/permissions", response_model=PermissionsView)
async def put_permissions(
    patch: PermissionsPatch,
    request: Request,
    svc: PermissionsService = Depends(_svc),
    uid: str = Depends(current_user),
) -> PermissionsView:
    _limit(request, "change", uid)
    return await svc.update(uid, patch, fresh_left_s=_fresh(request))


@router.post("/v1/passkeys/challenge", response_model=ChallengeView)
async def passkey_challenge(
    req: ChallengeRequest,
    request: Request,
    svc: PermissionsService = Depends(_svc),
    uid: str = Depends(current_user),
) -> ChallengeView:
    _limit(request, "ceremony", uid)

    async def approvals(aid: str) -> Any:
        return await _lookup(request, aid)

    return await svc.challenge(uid, req, approvals=approvals)


@router.post("/v1/passkeys/register/options", response_model=ChallengeView)
async def passkey_register_options(
    req: RegisterOptionsRequest,
    request: Request,
    svc: PermissionsService = Depends(_svc),
    uid: str = Depends(current_user),
) -> ChallengeView:
    _limit(request, "ceremony", uid)
    name = session_email(request, request.app.state.settings) or OWNER_NAME
    return await svc.register_options(
        uid, user_name=name, proof=req.proof, fresh_left_s=_fresh(request)
    )


@router.post("/v1/passkeys/register", response_model=PermissionsView)
async def passkey_register(
    req: RegisterRequest,
    request: Request,
    svc: PermissionsService = Depends(_svc),
    uid: str = Depends(current_user),
) -> PermissionsView:
    _limit(request, "ceremony", uid)
    return await svc.register(uid, req, fresh_left_s=_fresh(request))


@router.post("/v1/passkeys/reset", response_model=PermissionsView)
async def passkey_reset(
    request: Request, svc: PermissionsService = Depends(_svc), uid: str = Depends(current_user)
) -> PermissionsView:
    _limit(request, "ceremony", uid)
    return await svc.start_reset(uid, fresh_left_s=_fresh(request))


@router.post("/v1/passkeys/reset/cancel", response_model=PermissionsView)
async def passkey_reset_cancel(
    req: CancelResetRequest,
    request: Request,
    svc: PermissionsService = Depends(_svc),
    uid: str = Depends(current_user),
) -> PermissionsView:
    _limit(request, "ceremony", uid)
    return await svc.cancel_reset(uid, proof=req.proof, fresh_left_s=_fresh(request))


@router.post("/v1/passkeys/{credential_id}/remove", response_model=PermissionsView)
async def passkey_remove(
    credential_id: str,
    req: RemoveRequest,
    request: Request,
    svc: PermissionsService = Depends(_svc),
    uid: str = Depends(current_user),
) -> PermissionsView:
    _limit(request, "ceremony", uid)
    return await svc.remove(uid, credential_id, proof=req.proof, fresh_left_s=_fresh(request))


# ---- used by the approvals list (jarvis.api.routes) --------------------------------------------


async def mark_passkey_cards(
    request: Request, uid: str, cards: list[PendingApproval]
) -> list[PendingApproval]:
    """Which waiting cards the console must approve with a passkey. The gateway's approval guard
    decides for real at approval time; this only labels the button."""
    svc: PermissionsService | None = getattr(request.app.state, "permissions", None)
    if svc is None or not cards:
        return cards
    try:
        required = await svc.passkey_required(uid)
    except Exception as exc:  # noqa: BLE001 — label every irreversible card (fail closed)
        log.warning("passkey setting unreadable", extra={"error": type(exc).__name__})
        required = svc.available
    if not required:
        return cards
    return [
        c.model_copy(update={"passkey_required": c.tool_risk in (None, "irreversible")})
        for c in cards
    ]


def _err(status: int, body: dict[str, Any], headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content=body, headers=headers)


def install_permissions(app: FastAPI) -> None:
    """Mount /v1/permissions and /v1/passkeys, their per-owner limits and error mapping."""
    app.state.permission_limits = {
        "view": RateLimiter(VIEW_PER_MINUTE),
        "change": RateLimiter(CHANGE_PER_MINUTE),
        "ceremony": RateLimiter(CEREMONY_PER_MINUTE),
    }

    @app.exception_handler(PermissionRejected)
    async def _rejected(_: Request, exc: PermissionRejected) -> JSONResponse:
        return _err(422, {"error": "input_rejected", "detail": str(exc)})

    @app.exception_handler(PasskeysUnavailable)
    async def _unavailable(_: Request, exc: PasskeysUnavailable) -> JSONResponse:
        return _err(409, {"error": "passkeys_unavailable", "detail": str(exc)})

    @app.exception_handler(PasskeyRequired)
    async def _required(_: Request, exc: PasskeyRequired) -> JSONResponse:
        return _err(403, {"error": "passkey_required", "detail": str(exc)})

    @app.exception_handler(ProofRequired)
    async def _proof(_: Request, exc: ProofRequired) -> JSONResponse:
        return _err(403, {"error": "proof_required", "detail": str(exc), "reason": exc.reason})

    @app.exception_handler(PasskeyRejected)
    async def _bad_passkey(_: Request, exc: PasskeyRejected) -> JSONResponse:
        return _err(403, {"error": "passkey_rejected", "detail": str(exc), "reason": exc.reason})

    @app.exception_handler(PasskeyDataUnreadable)
    async def _unreadable(_: Request, exc: PasskeyDataUnreadable) -> JSONResponse:
        return _err(503, {"error": "passkeys_unreadable", "detail": UNREADABLE})

    @app.exception_handler(PermissionsRateLimited)
    async def _limited(_: Request, exc: PermissionsRateLimited) -> JSONResponse:
        retry = {"Retry-After": str(exc.retry_after)}
        return _err(429, {"error": "rate_limited", "detail": "too many requests"}, retry)

    app.include_router(router)


__all__ = [
    "build_permissions",
    "install_permissions",
    "mark_passkey_cards",
    "router",
]
