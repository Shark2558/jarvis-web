# src/jarvis/api/privacy.py
"""The privacy dashboard over HTTP (R2 D14; Layer 1 -> 3). Owner-only: `require_auth` +
`current_user` (no client user id is read); cookie writes need `X-Requested-With: JARVIS`.

GET  /v1/privacy                  {categories: [CategoryView], passkey_in_force, generated_at}
GET  /v1/privacy/{id}/export      JSON attachment {category, generated_at, data} (never a secret);
                                  for content (passkey-class) categories it needs the proof below,
                                  so a bare GET there is 403 (passkey_required / proof_required)
POST /v1/privacy/{id}/export      {proof?} -> the same; the proof (purpose privacy_export, target
                                  "export:<id>") or a Google sign-in < 5 minutes old is required
                                  for content categories; simple categories need neither
POST /v1/privacy/export-all       {proof?} -> JSON attachment of every exportable category except
                                  vault files; passkey check (purpose privacy_export) or a Google
                                  sign-in < 5 minutes old
POST /v1/privacy/{id}/delete      {rev, confirm?: "DELETE", proof?} -> {deleted, category,
                                  remaining} (remaining > 0: some are still there)

Errors {error, detail, reason?}: 403 console_only (a bearer token can look, never export or
delete), 403 not_deletable / no_export, 403 passkey_required / passkey_rejected / proof_required
{reason: reauth}, 404 not_found, 409 changed ("This changed - check again."), 422 input_rejected
(type DELETE), 429, 502 delete_failed, 503 unavailable.

`install_privacy(app)` mounts the routes; the integrator sets `app.state.privacy` to a
`PrivacyService` (registry of every category's source).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Path, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from jarvis.api.auth import fresh_sign_in_left, require_auth, session_email
from jarvis.api.identity import current_user
from jarvis.api.ratelimit import RateLimiter
from jarvis.permissions.models import PasskeyProof
from jarvis.privacy.service import (
    Changed,
    Deleted,
    DeleteFailed,
    NotDeletable,
    NotExportable,
    PrivacyService,
    PrivacyView,
    SourceUnavailable,
)

router = APIRouter(prefix="/v1/privacy", dependencies=[Depends(require_auth)])

VIEW_PER_MINUTE = 60
CHANGE_PER_MINUTE = 20
CATEGORY_ID = r"^[a-z][a-z0-9_]{0,31}$"
CONSOLE_ONLY = "Open the JARVIS console in your browser to do this."
CategoryPath = Path(pattern=CATEGORY_ID)


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeleteRequest(_In):
    rev: str = Field(min_length=1, max_length=64)
    confirm: str | None = Field(default=None, max_length=16)
    proof: PasskeyProof | None = None


class ExportAllRequest(_In):
    proof: PasskeyProof | None = None


class PrivacyRateLimited(Exception):
    def __init__(self, wait_s: float) -> None:
        self.retry_after = max(1, int(wait_s + 0.999))
        super().__init__("too many requests")


class ConsoleOnly(PermissionError):
    pass


def _svc(request: Request) -> PrivacyService:
    svc: PrivacyService | None = getattr(request.app.state, "privacy", None)
    if svc is None:
        raise LookupError("The privacy panel is not available on this server.")
    return svc


def _limit(request: Request, name: str, uid: str) -> None:
    allowed, wait = request.app.state.privacy_limits[name].allow(uid)
    if not allowed:
        raise PrivacyRateLimited(wait)


def _browser_only(request: Request) -> int | None:
    """Seconds left of a fresh Google sign-in in this browser; a bearer caller is refused."""
    s = request.app.state.settings
    if session_email(request, s) is None:
        raise ConsoleOnly(CONSOLE_ONLY)
    return fresh_sign_in_left(request, s)


def _attachment(body: dict[str, Any], name: str) -> Response:
    return Response(
        content=json.dumps(body, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "no-store",
        },
    )


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


@router.get("", response_model=PrivacyView)
async def get_privacy(
    request: Request, svc: PrivacyService = Depends(_svc), uid: str = Depends(current_user)
) -> PrivacyView:
    _limit(request, "view", uid)
    return await svc.view(uid)


async def _export_one(
    request: Request,
    svc: PrivacyService,
    uid: str,
    category_id: str,
    proof: PasskeyProof | None,
) -> Response:
    _limit(request, "change", uid)
    fresh = _browser_only(request)
    body = await svc.export(uid, category_id, proof=proof, fresh_left_s=fresh)
    return _attachment(body, f"jarvis-{category_id}-{_today()}.json")


@router.get("/{category_id}/export")
async def export_category(
    request: Request,
    category_id: str = CategoryPath,
    svc: PrivacyService = Depends(_svc),
    uid: str = Depends(current_user),
) -> Response:
    return await _export_one(request, svc, uid, category_id, None)


@router.post("/{category_id}/export")
async def export_category_with_proof(
    req: ExportAllRequest,
    request: Request,
    category_id: str = CategoryPath,
    svc: PrivacyService = Depends(_svc),
    uid: str = Depends(current_user),
) -> Response:
    return await _export_one(request, svc, uid, category_id, req.proof)


@router.post("/export-all")
async def export_all(
    req: ExportAllRequest,
    request: Request,
    svc: PrivacyService = Depends(_svc),
    uid: str = Depends(current_user),
) -> Response:
    _limit(request, "change", uid)
    fresh = _browser_only(request)
    body = await svc.export_all(uid, proof=req.proof, fresh_left_s=fresh)
    return _attachment(body, f"jarvis-everything-{_today()}.json")


@router.post("/{category_id}/delete", response_model=Deleted)
async def delete_category(
    req: DeleteRequest,
    request: Request,
    category_id: str = CategoryPath,
    svc: PrivacyService = Depends(_svc),
    uid: str = Depends(current_user),
) -> Deleted:
    _limit(request, "change", uid)
    fresh = _browser_only(request)
    return await svc.delete(
        uid, category_id, rev=req.rev, confirm=req.confirm, proof=req.proof, fresh_left_s=fresh
    )


def _err(
    status: int, code: str, detail: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"error": code, "detail": detail}, headers=headers
    )


def install_privacy(app: FastAPI) -> None:
    """Mount /v1/privacy with its per-owner limits and error mapping."""
    app.state.privacy_limits = {
        "view": RateLimiter(VIEW_PER_MINUTE),
        "change": RateLimiter(CHANGE_PER_MINUTE),
    }

    @app.exception_handler(ConsoleOnly)
    async def _console_only(_: Request, exc: ConsoleOnly) -> JSONResponse:
        return _err(403, "console_only", str(exc))

    @app.exception_handler(NotDeletable)
    async def _not_deletable(_: Request, exc: NotDeletable) -> JSONResponse:
        return _err(403, "not_deletable", str(exc))

    @app.exception_handler(NotExportable)
    async def _no_export(_: Request, exc: NotExportable) -> JSONResponse:
        return _err(403, "no_export", str(exc))

    @app.exception_handler(Changed)
    async def _changed(_: Request, exc: Changed) -> JSONResponse:
        return _err(409, "changed", str(exc))

    @app.exception_handler(SourceUnavailable)
    async def _unavailable(_: Request, exc: SourceUnavailable) -> JSONResponse:
        return _err(503, "unavailable", str(exc))

    @app.exception_handler(DeleteFailed)
    async def _failed(_: Request, exc: DeleteFailed) -> JSONResponse:
        return _err(502, "delete_failed", str(exc))

    @app.exception_handler(PrivacyRateLimited)
    async def _limited(_: Request, exc: PrivacyRateLimited) -> JSONResponse:
        return _err(429, "rate_limited", "too many requests", {"Retry-After": str(exc.retry_after)})

    app.include_router(router)


__all__ = ["DeleteRequest", "ExportAllRequest", "install_privacy", "router"]
