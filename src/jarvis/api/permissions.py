# src/jarvis/api/permissions.py
"""Owner permissions and passkeys over HTTP (slice 10 D; Layer 1 → 4). Owner-only: `require_auth`
+ `current_user` (no client user id is read); cookie writes need `X-Requested-With: JARVIS`.

GET  /v1/permissions                   PermissionsView: groups [{id, section, label, hint,
                                       irreversible, choices, effect, default}], require_passkey,
                                       passkeys [{id, label, created_at, last_used_at, backed_up}],
                                       passkeys_available, passkeys_note, can_reauth,
                                       fresh_sign_in_s, max_passkeys, label_max, rev
PUT  /v1/permissions                   {groups?: {id: allow|ask|deny}, require_passkey?, proof?}
                                       422 input_rejected (Allow on an irreversible group, unknown
                                       group / effect, requirement on without a passkey);
                                       403 proof_required when switching the requirement off
POST /v1/passkeys/challenge            {purpose: approve|remove|add|disable, approval_id?,
                                       credential_id?} → {challenge_id, public_key, expires_in_s}
                                       (navigator.credentials.get options; 2 minutes, single use)
POST /v1/passkeys/register/options     {proof?} → creation options (proof needed once a passkey
                                       exists: a check for "add", or a sign-in < 5 min old)
POST /v1/passkeys/register             {challenge_id, credential, label} → PermissionsView
POST /v1/passkeys/{id}/remove          {proof?} → PermissionsView (proof: a check for removing
                                       exactly this passkey, or a sign-in < 5 min old)

Approving an irreversible card while the requirement is in force: POST /v1/approvals/{id}/approve
{session_id, passkey: {challenge_id, credential}} (`guard_approval`, called by that route). Without
it: 403 passkey_required — what the CLI and scripts get (they can't do WebAuthn).

Errors: {error, detail, reason?}: 409 passkeys_unavailable, 403 passkey_required, 403
proof_required {reason: reauth|passkey}, 403 passkey_rejected {reason: replayed|expired|
wrong_action|unknown_passkey|failed}, 404 not_found, 429 rate_limited.
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
from jarvis.logging import get_logger
from jarvis.permissions.ceremony import RelyingParty
from jarvis.permissions.errors import (
    PasskeyRejected,
    PasskeyRequired,
    PasskeysUnavailable,
    PermissionRejected,
    ProofRequired,
)
from jarvis.permissions.models import (
    ChallengeRequest,
    ChallengeView,
    PasskeyProof,
    PermissionsPatch,
    PermissionsView,
    RegisterOptionsRequest,
    RegisterRequest,
    RemoveRequest,
)
from jarvis.permissions.passkeys import ChallengeStore, PasskeyStore
from jarvis.permissions.service import PermissionsService
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
    s: Settings, docs: Docs, *, audit: AuditTrail | None = None
) -> PermissionsService:
    """Choices, passkeys and challenges on the app's documents (Firestore in production); every
    change to them goes to the same audit chain as the tool calls."""
    p = s.firestore_prefix
    return PermissionsService(
        store=PermissionsStore(docs, prefix=p),
        passkeys=PasskeyStore(docs, prefix=p),
        challenges=ChallengeStore(docs, prefix=p),
        rp=RelyingParty.from_base_url(s.public_base_url),
        can_reauth=s.auth_mode is AuthMode.GOOGLE,
        audit=audit,
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
    return fresh_sign_in_left(request, request.app.state.settings)


async def _lookup(request: Request, approval_id: str) -> Any:
    gw = getattr(request.app.state.brain, "gateway", None)
    return await gw.gate.get(approval_id) if gw is not None else None


@router.get("/v1/permissions", response_model=PermissionsView)
async def get_permissions(
    request: Request, svc: PermissionsService = Depends(_svc), uid: str = Depends(current_user)
) -> PermissionsView:
    _limit(request, "view", uid)
    return await svc.view(uid, fresh_left_s=_fresh(request))


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


# ---- used by the approvals routes (jarvis.api.routes) -------------------------------------------


async def guard_approval(
    request: Request, uid: str, approval_id: str, proof: PasskeyProof | None
) -> None:
    """Before an approval runs: an irreversible card needs a passkey check made for exactly it
    while the owner requires one. A card that is gone or someone else's is left to the brain,
    which answers 404 and runs nothing."""
    svc: PermissionsService | None = getattr(request.app.state, "permissions", None)
    if svc is None:
        return
    action = await _lookup(request, approval_id)
    if action is None or not (action.scope or "").startswith(f"{uid}:"):
        return
    await svc.check_approval(uid, action, proof)


async def mark_passkey_cards(
    request: Request, uid: str, cards: list[PendingApproval]
) -> list[PendingApproval]:
    """Which waiting cards the console must approve with a passkey."""
    svc: PermissionsService | None = getattr(request.app.state, "permissions", None)
    if svc is None or not cards:
        return cards
    try:
        required = await svc.passkey_required(uid)
    except Exception as exc:  # noqa: BLE001 — the list stays readable; approving still checks
        log.warning("passkey setting unreadable", extra={"error": type(exc).__name__})
        return cards
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
    async def _proof(request: Request, exc: ProofRequired) -> JSONResponse:
        svc: PermissionsService | None = getattr(request.app.state, "permissions", None)
        reason = "reauth" if svc is not None and svc.can_reauth else "passkey"
        return _err(403, {"error": "proof_required", "detail": str(exc), "reason": reason})

    @app.exception_handler(PasskeyRejected)
    async def _bad_passkey(_: Request, exc: PasskeyRejected) -> JSONResponse:
        return _err(403, {"error": "passkey_rejected", "detail": str(exc), "reason": exc.reason})

    @app.exception_handler(PermissionsRateLimited)
    async def _limited(_: Request, exc: PermissionsRateLimited) -> JSONResponse:
        retry = {"Retry-After": str(exc.retry_after)}
        return _err(429, {"error": "rate_limited", "detail": "too many requests"}, retry)

    app.include_router(router)


__all__ = [
    "build_permissions",
    "guard_approval",
    "install_permissions",
    "mark_passkey_cards",
    "router",
]
