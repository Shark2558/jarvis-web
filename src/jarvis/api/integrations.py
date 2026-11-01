# src/jarvis/api/integrations.py
"""Linking the owner's Google account for the Calendar + Gmail tools (Layer 1 → 6).

GET  /connect/google                 signed-in owner → Google consent (offline, PKCE, login_hint)
GET  /connect/google/callback        store tokens iff the consenting account IS the signed-in owner
                                     AND every tool scope was granted; failures redirect to
                                     /?connect_error=<code> (browser landing); a grant from the
                                     wrong account is revoked at Google (best effort)
GET  /v1/integrations          {google: {connected, email, scopes, expires_at, needs_reconnect}}
POST /v1/integrations/google/disconnect   revoke at Google (best effort) + forget (CSRF header)

Mounted only when auth_mode=google. Separate from sign-in: `/auth/*` keeps `openid email`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from jarvis.api.auth import require_auth, session_email
from jarvis.api.identity import current_user, user_id_for_email
from jarvis.config import Settings
from jarvis.integrations.google import GoogleConnector, GoogleScopesMissing
from jarvis.logging import get_logger

log = get_logger(__name__)

router = APIRouter()
CONNECT_OWNER_KEY = "google_connect_owner"  # session: who started the consent flow


def _settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def _google(request: Request) -> GoogleConnector:
    conn = getattr(request.app.state, "google", None)
    if conn is None:
        raise HTTPException(404, "Google tools are not configured")
    return conn  # type: ignore[no-any-return]


def _callback_url(s: Settings) -> str:
    assert s.public_base_url is not None
    return s.public_base_url.rstrip("/") + "/connect/google/callback"


def _failed(code: str) -> RedirectResponse:
    """The browser arrives here from Google: land it back on the console with a reason code
    (not_started | wrong_account | oauth_failed | no_refresh_token | missing_scopes), never a
    JSON page. The console turns the code into a plain-English line."""
    return RedirectResponse(url=f"/?connect_error={code}", status_code=302)


# ---- connect flow ---------------------------------------------------------------------------


@router.get("/connect/google", include_in_schema=False)
async def connect(request: Request, s: Settings = Depends(_settings)) -> Any:
    _google(request)
    email = session_email(request, s)
    if email is None:  # a browser session only: scripts have no consent screen
        raise HTTPException(401, "sign in required")
    request.session[CONNECT_OWNER_KEY] = email
    return await request.app.state.oauth.google_tools.authorize_redirect(
        request,
        _callback_url(s),
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
        login_hint=email,
    )


@router.get("/connect/google/callback", include_in_schema=False)
async def connect_callback(
    request: Request, s: Settings = Depends(_settings), google: GoogleConnector = Depends(_google)
) -> Any:
    email = session_email(request, s)
    if email is None:
        raise HTTPException(401, "sign in required")
    started_by = request.session.pop(CONNECT_OWNER_KEY, None)
    if started_by != email:
        # The flow was started by another account in this browser (or not at all): a state
        # minted for one owner must never link tokens to a different one.
        log.warning("google connect refused: owner changed mid-flow")
        return _failed("not_started")
    try:
        token = await request.app.state.oauth.google_tools.authorize_access_token(request)
    except Exception as exc:  # noqa: BLE001 — authlib raises many types; none may leak detail
        log.warning("google connect failed", extra={"reason": type(exc).__name__})
        return _failed("oauth_failed")

    info = token.get("userinfo") or {}
    consented = str(info.get("email") or "").lower()
    if not consented or not info.get("email_verified") or consented != email.lower():
        log.warning("google connect refused: consenting account is not the signed-in owner")
        # someone else's grant is never kept: hand it back to Google (best effort)
        await google.revoke(str(token.get("refresh_token") or token.get("access_token") or ""))
        return _failed("wrong_account")
    try:
        await google.save(user_id_for_email(email), email=email, token=token)
    except GoogleScopesMissing:
        log.warning("google connect refused: not every tool scope was granted")
        return _failed("missing_scopes")
    except ValueError:
        log.warning("google connect: no refresh token in the response")
        return _failed("no_refresh_token")
    return RedirectResponse(url="/?connected=google", status_code=302)


# ---- status / disconnect --------------------------------------------------------------------


class GoogleStatus(BaseModel):
    connected: bool
    email: str | None
    scopes: list[str]
    expires_at: float | None
    needs_reconnect: bool


class Integrations(BaseModel):
    google: GoogleStatus


@router.get("/v1/integrations", response_model=Integrations, dependencies=[Depends(require_auth)])
async def integrations(
    google: GoogleConnector = Depends(_google), uid: str = Depends(current_user)
) -> Integrations:
    return Integrations(google=GoogleStatus(**await google.status(uid)))


@router.post("/v1/integrations/google/disconnect", dependencies=[Depends(require_auth)])
async def disconnect(
    google: GoogleConnector = Depends(_google), uid: str = Depends(current_user)
) -> dict[str, Any]:
    await google.disconnect(uid)
    return {"ok": True, "google": {"connected": False}}
