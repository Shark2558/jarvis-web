# src/jarvis/integrations/google.py
"""Google account link (Layer 6): OAuth client for the tool scopes, token refresh, revoke, and
one authenticated REST door the Calendar and Gmail tools go through.

Direct REST via httpx — no Google SDK (the remote MCP servers are still Developer Preview; see
docs/plans/phase2-slice6-gmail-calendar.md). Vendor error text never leaves this module: tools
and the UI see short friendly messages. Tokens are never logged.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from typing import Any

import httpx
from pydantic import SecretStr

from jarvis.config import AuthMode, Settings
from jarvis.integrations.vault import GoogleTokens, TokenStore, VaultError
from jarvis.logging import get_logger

log = get_logger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUER = "https://accounts.google.com"

# Every API scope the tools need. gmail.compose already permits messages.send (Google lists it
# among users.messages.send's scopes), so the separate gmail.send scope is not requested.
REQUIRED_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
)
# Requested on connect but NOT required: a link without them keeps every slice 6 tool. gmail.insert
# lets the morning brief (slice 7) add one message to the owner's own inbox — it has no
# recipient, so it cannot send anything to anyone.
INSERT_SCOPE = "https://www.googleapis.com/auth/gmail.insert"
OPTIONAL_SCOPES: tuple[str, ...] = (INSERT_SCOPE,)
# Google accepts users.messages.insert with any of these.
INSERT_CAPABLE_SCOPES = frozenset(
    {INSERT_SCOPE, "https://www.googleapis.com/auth/gmail.modify", "https://mail.google.com/"}
)
# openid+email so the callback can prove WHICH Google account consented (must equal the owner).
TOOL_SCOPES: tuple[str, ...] = ("openid", "email", *REQUIRED_SCOPES, *OPTIONAL_SCOPES)


def can_insert(scopes: Iterable[str]) -> bool:
    """True when the granted scopes allow messages.insert (inbox delivery of the brief)."""
    return not INSERT_CAPABLE_SCOPES.isdisjoint(scopes)


HTTP_TIMEOUT_S = 15.0
REFRESH_SKEW_S = 60.0  # refresh when the access token has less than this left
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
# Only calls that change nothing are retried: a 5xx after messages.send / drafts.create /
# events.insert may come AFTER Google acted, and a retry would send or create it twice.
SAFE_METHODS = frozenset({"GET", "HEAD"})

NOT_CONNECTED_MSG = (
    "Google is not connected. Connect it in the panel (Integrations) to use calendar and mail."
)
RECONNECT_MSG = "Google needs reconnecting (panel → Integrations)."


class GoogleNotConnected(RuntimeError):
    """No usable token for this owner: never linked, disconnected, or refresh was refused."""


class GoogleScopesMissing(ValueError):
    """Granular consent: the owner left some permissions unticked. Nothing is stored."""


class GoogleAPIError(RuntimeError):
    """A Google call failed; the message is already owner-friendly and vendor-text free."""


_FRIENDLY: dict[int, str] = {
    400: "Google rejected the request as invalid.",
    401: "Google rejected the credentials.",
    403: "Google refused: missing permission for that action (reconnect to grant it).",
    404: "Google could not find that item (not found).",
    409: "Google reports a conflict with an existing item.",
    410: "That item is gone (already deleted).",
    412: "That item changed meanwhile; fetch it again before updating.",
    429: "Google is rate limiting requests right now; try again shortly.",
}


def _friendly(status: int) -> str:
    if status in _FRIENDLY:
        return _FRIENDLY[status]
    if status >= 500:
        return "Google's service is temporarily unavailable; try again shortly."
    return f"Google returned an unexpected status ({status})."


class GoogleConnector:
    """Per-deployment: one OAuth client; per-owner tokens via `TokenStore`."""

    def __init__(
        self,
        store: TokenStore,
        *,
        client_id: str,
        client_secret: SecretStr,
        http: httpx.AsyncClient | None = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self._client_id = client_id
        self._client_secret = client_secret
        self.http = http or httpx.AsyncClient(timeout=HTTP_TIMEOUT_S)
        self._now = now

    # ---- status / lifecycle --------------------------------------------------------------

    async def _load(self, user_id: str) -> GoogleTokens | None | VaultError:
        """Stored tokens, None when there are none, or the VaultError when the entry cannot be
        decrypted (key rotated, document tampered): unusable, so the owner must reconnect."""
        try:
            return await self.store.get(user_id)
        except VaultError as exc:
            log.error("google token vault entry unreadable; owner must reconnect")
            return exc

    async def status(self, user_id: str) -> dict[str, Any]:
        t = await self._load(user_id)
        if t is None or isinstance(t, VaultError):
            return {
                "connected": False,
                "email": None,
                "scopes": [],
                "expires_at": None,
                "needs_reconnect": isinstance(t, VaultError),
            }
        return {
            "connected": True,
            "email": t.email,
            "scopes": list(t.scopes),
            "expires_at": t.expires_at,
            "needs_reconnect": t.needs_reconnect,
        }

    async def save(self, user_id: str, *, email: str, token: dict[str, Any]) -> None:
        """Persist an Authlib token response. A refresh token is mandatory: without it the
        link would silently die within the hour."""
        refresh = token.get("refresh_token")
        access = token.get("access_token")
        if not refresh or not access:
            raise ValueError("Google did not return a refresh token; reconnect with consent")
        granted = set(str(token.get("scope", "")).split())
        missing = [s for s in REQUIRED_SCOPES if s not in granted]
        if missing:
            short = ", ".join(s.rsplit("/", 1)[-1] for s in missing)
            raise GoogleScopesMissing(f"Google did not grant: {short}")
        expires_at = token.get("expires_at")
        if expires_at is None:
            expires_at = self._now() + float(token.get("expires_in", 0))
        scopes = str(token.get("scope", "")).split()
        await self.store.put(
            user_id,
            GoogleTokens(
                email=email.lower(),
                access_token=SecretStr(str(access)),
                refresh_token=SecretStr(str(refresh)),
                expires_at=float(expires_at),
                scopes=scopes,
            ),
        )
        log.info("google linked", extra={"scopes": len(scopes)})

    async def disconnect(self, user_id: str) -> None:
        """Revoke at Google (best effort) and forget the tokens (always)."""
        t = await self._load(user_id)
        if t is None:
            return
        if isinstance(t, VaultError):
            await self.store.delete(user_id)  # nothing usable to revoke; forget it
            return
        await self.revoke(t.refresh_token.get_secret_value())
        await self.store.delete(user_id)
        log.info("google unlinked")

    async def revoke(self, token: str) -> None:
        """Best effort: ask Google to revoke a token (and with it the grant). Never raises."""
        if not token:
            return
        try:
            await self.http.post(REVOKE_URL, data={"token": token}, timeout=HTTP_TIMEOUT_S)
        except httpx.HTTPError as exc:
            log.warning("google revoke failed", extra={"reason": type(exc).__name__})

    # ---- tokens --------------------------------------------------------------------------

    async def access_token(self, user_id: str) -> str:
        t = await self._load(user_id)
        if t is None:
            raise GoogleNotConnected(NOT_CONNECTED_MSG)
        if isinstance(t, VaultError) or t.needs_reconnect:
            raise GoogleNotConnected(RECONNECT_MSG)
        if t.expires_at - self._now() > REFRESH_SKEW_S:
            return t.access_token.get_secret_value()
        return await self._refresh(user_id, t)

    async def _refresh(self, user_id: str, t: GoogleTokens) -> str:
        try:
            r = await self.http.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": t.refresh_token.get_secret_value(),
                    "client_id": self._client_id,
                    "client_secret": self._client_secret.get_secret_value(),
                },
                timeout=HTTP_TIMEOUT_S,
            )
        except httpx.HTTPError as exc:
            log.warning("google token refresh unreachable", extra={"reason": type(exc).__name__})
            raise GoogleAPIError("Could not reach Google to refresh access.") from exc
        if r.status_code == 200:
            body = r.json()
            fresh = t.model_copy(
                update={
                    "access_token": SecretStr(str(body["access_token"])),
                    "expires_at": self._now() + float(body.get("expires_in", 0)),
                    "refresh_token": SecretStr(str(body.get("refresh_token")))
                    if body.get("refresh_token")
                    else t.refresh_token,
                    "needs_reconnect": False,
                }
            )
            await self.store.put(user_id, fresh)
            return fresh.access_token.get_secret_value()
        err = _json_error(r)
        if r.status_code in (400, 401) and err in ("invalid_grant", "invalid_token"):
            # Testing-mode OAuth apps hand out 7-day refresh tokens; this is how they die.
            await self.store.put(user_id, t.model_copy(update={"needs_reconnect": True}))
            log.warning("google refresh token no longer valid; owner must reconnect")
            raise GoogleNotConnected(RECONNECT_MSG)
        log.warning("google token refresh failed", extra={"status": r.status_code})
        raise GoogleAPIError(_friendly(r.status_code))

    # ---- REST door -----------------------------------------------------------------------

    async def request(
        self,
        user_id: str,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        retry_safe: bool | None = None,
    ) -> Any:
        """One Google REST call: bearer token, 15 s timeout, one forced refresh on 401 (not
        processed, so safe to resend), and one retry on 429/5xx ONLY for safe calls: GET/HEAD,
        or a read-only POST that passes `retry_safe=True` (freeBusy). Returns parsed JSON
        ({} for an empty body)."""
        safe = method.upper() in SAFE_METHODS if retry_safe is None else retry_safe
        token = await self.access_token(user_id)
        r = await self._send(method, url, token, params, json)
        if r.status_code == 401:
            t = await self._load(user_id)
            if t is None or isinstance(t, VaultError):
                raise GoogleNotConnected(RECONNECT_MSG)
            token = await self._refresh(user_id, t)
            r = await self._send(method, url, token, params, json)
        elif r.status_code in RETRY_STATUSES and safe:
            r = await self._send(method, url, token, params, json)
        if r.status_code >= 400:
            log.warning(
                "google api error", extra={"status": r.status_code, "path": httpx.URL(url).path}
            )
            raise GoogleAPIError(_friendly(r.status_code))
        if not r.content:
            return {}
        try:
            return r.json()
        except ValueError as exc:
            raise GoogleAPIError("Google returned an unreadable response.") from exc

    async def _send(
        self,
        method: str,
        url: str,
        token: str,
        params: dict[str, Any] | None,
        json: Any | None,
    ) -> httpx.Response:
        try:
            return await self.http.request(
                method,
                url,
                params=params,
                json=json,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=HTTP_TIMEOUT_S,
            )
        except httpx.HTTPError as exc:
            log.warning("google api unreachable", extra={"reason": type(exc).__name__})
            raise GoogleAPIError("Could not reach Google; try again shortly.") from exc


def _json_error(r: httpx.Response) -> str:
    try:
        body = r.json()
    except ValueError:
        return ""
    return str(body.get("error", "")) if isinstance(body, dict) else ""


# ---- wiring ------------------------------------------------------------------------------


TOKEN_KEY_MISSING_MSG = (
    "JARVIS_TOKEN_KEY is not set: the Google Calendar/Gmail tools are OFF and the Integrations "
    "panel shows 'Not available'. Re-run deploy/cloudrun.sh (it creates and binds the "
    "jarvis-token-key secret) to switch them on."
)
DEV_MEMORY_TOKENS_MSG = (
    "dev: no JARVIS_TOKEN_KEY, so Google links are kept in memory and end with the process."
)


def _google_tools_requested(s: Settings) -> bool:
    return bool(
        s.google_tools_enabled
        and s.auth_mode is AuthMode.GOOGLE
        and s.google_client_id
        and s.google_client_secret is not None
    )


def google_tools_configured(s: Settings) -> bool:
    """Tools, /connect and /v1/integrations are on. Outside dev they also need the vault key:
    without it there is nowhere safe to keep the tokens, so they stay off (never a crash)."""
    return _google_tools_requested(s) and (s.token_key is not None or s.env == "dev")


def google_tools_startup_note(s: Settings) -> str | None:
    """The one start-up warning about the token key, or None when there is nothing to say."""
    if not _google_tools_requested(s) or s.token_key is not None:
        return None
    return DEV_MEMORY_TOKENS_MSG if s.env == "dev" else TOKEN_KEY_MISSING_MSG


def build_google_connector(s: Settings, store: TokenStore) -> GoogleConnector | None:
    if not google_tools_configured(s):
        return None
    assert s.google_client_id and s.google_client_secret is not None
    return GoogleConnector(
        store, client_id=s.google_client_id, client_secret=s.google_client_secret
    )


def register_tools_oauth(oauth: Any, s: Settings) -> None:
    """Second Authlib client, `google_tools`: same credentials as sign-in, tool scopes, PKCE.
    Sign-in (`google`, `openid email`) is untouched."""
    assert s.google_client_secret is not None
    oauth.register(
        name="google_tools",
        client_id=s.google_client_id,
        client_secret=s.google_client_secret.get_secret_value(),
        client_kwargs={"scope": " ".join(TOOL_SCOPES), "code_challenge_method": "S256"},
        authorize_url=AUTHORIZE_URL,
        access_token_url=TOKEN_URL,
        jwks_uri=JWKS_URL,
        userinfo_endpoint="https://openidconnect.googleapis.com/v1/userinfo",
        issuer=ISSUER,
    )


__all__ = [
    "AUTHORIZE_URL",
    "INSERT_CAPABLE_SCOPES",
    "INSERT_SCOPE",
    "OPTIONAL_SCOPES",
    "REQUIRED_SCOPES",
    "REVOKE_URL",
    "TOKEN_URL",
    "TOOL_SCOPES",
    "GoogleAPIError",
    "GoogleConnector",
    "GoogleNotConnected",
    "GoogleScopesMissing",
    "build_google_connector",
    "can_insert",
    "google_tools_configured",
    "google_tools_startup_note",
    "register_tools_oauth",
]
