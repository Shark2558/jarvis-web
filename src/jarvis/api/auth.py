# src/jarvis/api/auth.py
"""Who is allowed to talk to JARVIS (Layer 1 surface; cross-cutting security).

Two credentials are accepted:
  * a bearer token (CLI, evals, scripts) — constant-time compared with JARVIS_API_TOKEN;
  * a signed browser session cookie, issued only after a Google sign-in whose verified email
    is on JARVIS_OWNER_EMAILS. Google *authenticates*; the allowlist *authorizes*.

Cookie-authenticated writes must also carry `X-Requested-With: JARVIS` (CSRF defence: a
cross-site form cannot set custom headers, and we serve no CORS headers).
"""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from jarvis.config import AuthMode, Settings
from jarvis.logging import get_logger

log = get_logger(__name__)

CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "JARVIS"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
SESSION_EMAIL_KEY = "email"
# Pinned endpoints (no discovery fetch at startup → boots offline, fails only at sign-in time).
GOOGLE_ENDPOINTS = {
    "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
    "access_token_url": "https://oauth2.googleapis.com/token",
    "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
    "userinfo_endpoint": "https://openidconnect.googleapis.com/v1/userinfo",
    "issuer": "https://accounts.google.com",
}

_bearer = HTTPBearer(auto_error=False)


class CSRFRejected(Exception):
    """Cookie-authenticated write without the anti-CSRF header."""


def _settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def _bearer_ok(creds: HTTPAuthorizationCredentials | None, s: Settings) -> bool:
    if creds is None or s.api_token is None:
        return False
    return secrets.compare_digest(creds.credentials, s.api_token.get_secret_value())


def session_email(request: Request, s: Settings) -> str | None:
    """Email of the signed-in owner, or None. Re-checks the allowlist on every request so
    removing an email from config logs that browser out immediately."""
    if s.auth_mode is not AuthMode.GOOGLE or "session" not in request.scope:
        return None
    email = request.session.get(SESSION_EMAIL_KEY)
    if isinstance(email, str) and email.lower() in s.owner_emails:
        return email
    return None


async def require_auth(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    s: Settings = Depends(_settings),
) -> None:
    if _bearer_ok(creds, s):
        return
    if session_email(request, s) is not None:
        if request.method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
            raise CSRFRejected()
        return
    if s.api_token is None and s.auth_mode is AuthMode.TOKEN:
        if s.env == "dev":
            return  # local dev with no token configured
        raise HTTPException(500, "server misconfigured: no API token")
    raise HTTPException(401, "sign in required")


# ---- Google OIDC routes (mounted only when auth_mode == google) -----------------------------

auth_router = APIRouter(prefix="/auth")


def build_oauth(s: Settings) -> Any:
    """Authlib client. Kept behind a function so tests can swap the token exchange."""
    from authlib.integrations.starlette_client import OAuth

    oauth = OAuth()
    assert s.google_client_secret is not None  # enforced by require_prod_invariants
    oauth.register(
        name="google",
        client_id=s.google_client_id,
        client_secret=s.google_client_secret.get_secret_value(),
        client_kwargs={
            "scope": "openid email",
            "prompt": "select_account",
            "code_challenge_method": "S256",  # PKCE
        },
        **GOOGLE_ENDPOINTS,
    )
    return oauth


def _oauth(request: Request) -> Any:
    return request.app.state.oauth


def _callback_url(s: Settings) -> str:
    assert s.public_base_url is not None
    return s.public_base_url.rstrip("/") + "/auth/callback"


@auth_router.get("/login")
async def login(request: Request, s: Settings = Depends(_settings)) -> Any:
    return await _oauth(request).google.authorize_redirect(request, _callback_url(s))


@auth_router.get("/callback")
async def callback(request: Request, s: Settings = Depends(_settings)) -> Any:
    try:
        token = await _oauth(request).google.authorize_access_token(request)
    except Exception as exc:  # authlib raises many error types; none should leak detail
        log.warning("google sign-in failed", extra={"reason": type(exc).__name__})
        raise HTTPException(400, "sign-in could not be completed; please try again") from exc

    info = token.get("userinfo") or {}
    email = str(info.get("email") or "").lower()
    verified = bool(info.get("email_verified"))
    request.session.clear()
    if not email or not verified or email not in s.owner_emails:
        log.warning(
            "sign-in refused", extra={"verified": verified, "listed": email in s.owner_emails}
        )
        return JSONResponse(
            status_code=403,
            content={"error": "not_owner", "detail": "This JARVIS belongs to someone else."},
        )
    request.session[SESSION_EMAIL_KEY] = email
    log.info("owner signed in")
    return RedirectResponse(url="/", status_code=302)


@auth_router.post("/logout")
async def logout(request: Request) -> JSONResponse:
    if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise CSRFRejected()
    request.session.clear()
    return JSONResponse({"ok": True})
