# src/jarvis/api/auth.py
"""Who is allowed to talk to JARVIS (Layer 1 surface; cross-cutting security).

Two credentials are accepted:
  * a bearer token (CLI, evals, scripts) — constant-time compared with JARVIS_API_TOKEN;
  * a signed browser session cookie, issued only after a Google sign-in whose verified email
    is on JARVIS_OWNER_EMAILS. Google *authenticates*; the allowlist *authorizes*.

Cookie-authenticated writes must also carry `X-Requested-With: JARVIS` (CSRF defence: a
cross-site form cannot set custom headers, and we serve no CORS headers).

Slice 10 D: the cookie also records WHEN the owner last authenticated with Google (`auth_at`: the
ID token's `auth_time` when Google sends one, else the moment the sign-in completed). For 5
minutes after that, a sign-in stands in for a passkey to lower protection (remove a passkey,
switch the requirement off) — the recovery path when a passkey is lost. `/auth/login?reauth=1`
asks Google to authenticate again (`max_age=0`) and returns to `/?reauth=done`.
"""

from __future__ import annotations

import secrets
import time
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
SESSION_ISSUED_KEY = "iat"
SESSION_ABSOLUTE_MAX_S = 24 * 60 * 60  # the cookie's max_age slides; this one does not
SESSION_AUTH_AT_KEY = "auth_at"  # when Google last authenticated the owner (epoch seconds)
SESSION_REAUTH_KEY = "reauth"  # a re-authentication is under way (set by /auth/login?reauth=1)
FRESH_SIGN_IN_S = 5 * 60
REAUTH_MAX_AGE_S = 0  # OIDC max_age: Google must authenticate the owner again now
AUTH_TIME_OLDEST_S = 30 * 24 * 60 * 60
AUTH_TIME_SKEW_S = 60


def _now() -> float:
    return time.time()


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
    issued = request.session.get(SESSION_ISSUED_KEY)
    if not isinstance(email, str) or not isinstance(issued, int | float):
        return None
    if _now() - issued > SESSION_ABSOLUTE_MAX_S:
        request.session.clear()  # absolute lifetime reached; replaying a stolen cookie ends here
        return None
    if email.lower() in s.owner_emails:
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


def fresh_sign_in_left(request: Request, s: Settings) -> int | None:
    """Seconds left in which the owner's last Google sign-in counts as proof (0 when it is too
    old or unknown); None when the caller is not a signed-in browser (bearer token)."""
    if session_email(request, s) is None:
        return None
    at = request.session.get(SESSION_AUTH_AT_KEY)
    if not isinstance(at, int | float) or isinstance(at, bool):
        return 0
    return max(0, int(FRESH_SIGN_IN_S - (_now() - at)))


def _auth_at(info: Any, now: float) -> float:
    """Google's `auth_time` when it is sane, else now (the sign-in just completed)."""
    at = info.get("auth_time") if hasattr(info, "get") else None
    if isinstance(at, int | float) and not isinstance(at, bool):
        if now - AUTH_TIME_OLDEST_S < at <= now + AUTH_TIME_SKEW_S:
            return float(min(at, now))
    return now


@auth_router.get("/login")
async def login(request: Request, s: Settings = Depends(_settings), reauth: int = 0) -> Any:
    extra: dict[str, Any] = {}
    if reauth:
        request.session[SESSION_REAUTH_KEY] = True
        extra["max_age"] = REAUTH_MAX_AGE_S
    return await _oauth(request).google.authorize_redirect(request, _callback_url(s), **extra)


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
    was_reauth = request.session.get(SESSION_REAUTH_KEY) is True
    request.session.clear()
    if not email or not verified or email not in s.owner_emails:
        log.warning(
            "sign-in refused", extra={"verified": verified, "listed": email in s.owner_emails}
        )
        return JSONResponse(
            status_code=403,
            content={"error": "not_owner", "detail": "This JARVIS belongs to someone else."},
        )
    now = _now()
    request.session[SESSION_EMAIL_KEY] = email
    request.session[SESSION_ISSUED_KEY] = now
    request.session[SESSION_AUTH_AT_KEY] = _auth_at(info, now)
    log.info("owner signed in", extra={"reauth": was_reauth})
    return RedirectResponse(url="/?reauth=done" if was_reauth else "/", status_code=302)


@auth_router.post("/logout")
async def logout(request: Request) -> JSONResponse:
    if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise CSRFRejected()
    request.session.clear()
    return JSONResponse({"ok": True})
