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
from jarvis.integrations import google_errors
from jarvis.integrations.google_errors import UsedUp
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
# The to-do list (slice 10 C): Google Tasks read + write. Optional like gmail.insert: a link
# without it keeps every other tool; the to-do tools then answer "grant access".
TASKS_SCOPE = "https://www.googleapis.com/auth/tasks"
# Slice 12 D7: two more optional Grants, read only. Contacts: people.searchContacts (verified
# 2026-11-03 against developers.google.com/people/api/rest/v1/people/searchContacts: contacts or
# contacts.readonly). YouTube: the owner's own playlists (builder B's tools).
CONTACTS_SCOPE = "https://www.googleapis.com/auth/contacts.readonly"
YOUTUBE_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
CONTACTS_CAPABLE_SCOPES = frozenset({CONTACTS_SCOPE, "https://www.googleapis.com/auth/contacts"})
# Any of these lets playlists.list(mine) / playlistItems.list read (the same set as builder B's).
YOUTUBE_READ_SCOPES = frozenset(
    {
        YOUTUBE_SCOPE,
        "https://www.googleapis.com/auth/youtube",
        "https://www.googleapis.com/auth/youtube.force-ssl",
    }
)
# The optional permissions an owner adds with Integrations → Grant (`/connect/google?add=<name>`):
# exactly these names, each ONE scope asked for (the read-only one). Order here is the order they
# are asked for.
GRANTS: dict[str, str] = {
    "tasks": TASKS_SCOPE,
    "contacts": CONTACTS_SCOPE,
    "youtube": YOUTUBE_SCOPE,
}
# Review C8: one notion of "has this Grant" — any of these scopes held satisfies it (a wider
# scope granted to the same app counts), for `held_grants` and every `can_use_*` alike.
GRANT_ACCEPTS: dict[str, frozenset[str]] = {
    "tasks": frozenset({TASKS_SCOPE}),  # tasks.readonly would not do: the to-do tools write
    "contacts": CONTACTS_CAPABLE_SCOPES,
    "youtube": YOUTUBE_READ_SCOPES,
}
OPTIONAL_SCOPES: tuple[str, ...] = (INSERT_SCOPE, *GRANTS.values())
# Google accepts users.messages.insert with any of these.
INSERT_CAPABLE_SCOPES = frozenset(
    {INSERT_SCOPE, "https://www.googleapis.com/auth/gmail.modify", "https://mail.google.com/"}
)
# openid+email so the callback can prove WHICH Google account consented (must equal the owner).
# Every scope a link may hold:
TOOL_SCOPES: tuple[str, ...] = ("openid", "email", *REQUIRED_SCOPES, *OPTIONAL_SCOPES)
# What a plain (re)connect asks for — unchanged by slice 10 (review L8). A Grant's scope is asked
# for only by its explicit Grant, or when the link being renewed already holds it (slice 12 D7).
CONNECT_SCOPES: tuple[str, ...] = ("openid", "email", *REQUIRED_SCOPES, INSERT_SCOPE)


def connect_scopes(grants: Iterable[str] = ()) -> str:
    """The scope string for one consent request (with include_granted_scopes): the plain set plus
    the named Grants (each once, in `GRANTS` order). An unknown name is a ValueError."""
    wanted = set(grants)
    unknown = wanted - GRANTS.keys()
    if unknown:
        raise ValueError(f"unknown grant: {', '.join(sorted(unknown))}")
    return " ".join((*CONNECT_SCOPES, *(s for n, s in GRANTS.items() if n in wanted)))


def grant_name(raw: object) -> str | None:
    """`raw` when it is exactly one allow-listed Grant name, else None (never guessed)."""
    return raw if isinstance(raw, str) and raw in GRANTS else None


def held_grants(scopes: Iterable[str]) -> frozenset[str]:
    """The Grants a link's scopes already hold (`GRANT_ACCEPTS`); renewing the link asks for
    each again — by its one read-only scope (`GRANTS`), never a wider one it happens to hold."""
    have = set(scopes)
    return frozenset(n for n, ok in GRANT_ACCEPTS.items() if not ok.isdisjoint(have))


def can_insert(scopes: Iterable[str]) -> bool:
    """True when the granted scopes allow messages.insert (inbox delivery of the brief)."""
    return not INSERT_CAPABLE_SCOPES.isdisjoint(scopes)


def can_use_tasks(scopes: Iterable[str]) -> bool:
    """True when the granted scopes allow reading AND changing the owner's Google Tasks
    (tasks.readonly alone would not do: the to-do tools write)."""
    return "tasks" in held_grants(scopes)


def can_use_contacts(scopes: Iterable[str]) -> bool:
    """True when the granted scopes allow searching the owner's Google Contacts."""
    return "contacts" in held_grants(scopes)


def can_use_youtube(scopes: Iterable[str]) -> bool:
    """True when the granted scopes let JARVIS read the owner's own YouTube playlists."""
    return "youtube" in held_grants(scopes)


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


class GoogleServiceDisabled(GoogleAPIError):
    """403 because the API is not switched on in the Cloud project (not a missing scope).
    Decided from Google's reason codes only; the vendor message is never shown."""


class GoogleNotFound(GoogleAPIError):
    """404 / 410: the item is not there (never existed, or deleted). Slice 11: a restore checks
    whether a to-do's parent or subtasks still exist."""


class GoogleUncertain(GoogleAPIError):
    """Slice 11 fix: Google may or may not have made the change — no answer (timeout, the
    connection dropped) or a 5xx. A delete is checked by reading the item again."""


class GoogleConflict(GoogleAPIError):
    """409: an item with that id already exists (slice 11: a restore that already happened)."""


class GoogleInvalid(GoogleAPIError):
    """400: Google refused the request as invalid (slice 11: a restore retries without the
    `previous` sibling it named)."""


class GoogleQuotaExceeded(GoogleAPIError):
    """Slice 12: Google says a per-day or per-month quota of the project is gone (`period`), from
    its machine-readable fields only (`google_errors.used_up`). YouTube's units are the project's,
    whichever credential spent them, so the allowance ledger closes them too."""

    def __init__(self, message: str, *, period: UsedUp) -> None:
        super().__init__(message)
        self.period: UsedUp = period


def never_sent(exc: BaseException) -> bool:
    """Slice 12: a `request` that failed before its request left JARVIS (the connection was
    refused), so Google did nothing with it — the allowance ledger gives its unit back."""
    return isinstance(exc, GoogleUncertain) and isinstance(
        exc.__cause__, httpx.ConnectError | httpx.ConnectTimeout
    )


GONE_STATUSES = frozenset({404, 410})
SERVICE_DISABLED_REASONS = frozenset({"accessNotConfigured", "SERVICE_DISABLED"})
SERVICE_OFF_MSG = "That Google service is not switched on for your JARVIS project yet."


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
            if r.status_code == 403 and not SERVICE_DISABLED_REASONS.isdisjoint(_reasons(r)):
                raise GoogleServiceDisabled(SERVICE_OFF_MSG)
            if r.status_code in (403, 429):  # slice 12: a used-up quota or a short-term limit
                err = google_errors.envelope(r.content)
                if (period := google_errors.used_up(err)) is not None:
                    raise GoogleQuotaExceeded(google_errors.USED_UP_MSG[period], period=period)
                if google_errors.rate_limited(err):
                    raise GoogleAPIError(_friendly(429))
            raise _error_for(r.status_code)
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
            raise GoogleUncertain("Could not reach Google; try again shortly.") from exc


def _error_for(status: int) -> GoogleAPIError:
    """The class a failed call raises (its words are always ours, never Google's)."""
    if status in GONE_STATUSES:
        return GoogleNotFound(_friendly(status))
    if status == 409:
        return GoogleConflict(_friendly(status))
    if status == 400:
        return GoogleInvalid(_friendly(status))
    if status >= 500:
        return GoogleUncertain(_friendly(status))
    return GoogleAPIError(_friendly(status))


def _reasons(r: httpx.Response) -> set[str]:
    """Google's machine-readable error reasons (errors[].reason, details[].reason); never text."""
    try:
        err = r.json().get("error")
    except (ValueError, AttributeError):
        return set()
    if not isinstance(err, dict):
        return set()
    found: set[str] = set()
    for key in ("errors", "details"):
        items = err.get(key)
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and isinstance(item.get("reason"), str):
                found.add(item["reason"][:64])
    return found


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
        client_kwargs={"scope": connect_scopes(), "code_challenge_method": "S256"},
        authorize_url=AUTHORIZE_URL,
        access_token_url=TOKEN_URL,
        jwks_uri=JWKS_URL,
        userinfo_endpoint="https://openidconnect.googleapis.com/v1/userinfo",
        issuer=ISSUER,
    )


__all__ = [
    "AUTHORIZE_URL",
    "CONNECT_SCOPES",
    "CONTACTS_CAPABLE_SCOPES",
    "CONTACTS_SCOPE",
    "GRANTS",
    "GRANT_ACCEPTS",
    "INSERT_CAPABLE_SCOPES",
    "INSERT_SCOPE",
    "OPTIONAL_SCOPES",
    "REQUIRED_SCOPES",
    "REVOKE_URL",
    "TASKS_SCOPE",
    "TOKEN_URL",
    "TOOL_SCOPES",
    "YOUTUBE_READ_SCOPES",
    "YOUTUBE_SCOPE",
    "GoogleAPIError",
    "GoogleConflict",
    "GoogleConnector",
    "GoogleInvalid",
    "GoogleNotConnected",
    "GoogleNotFound",
    "GoogleQuotaExceeded",
    "GoogleScopesMissing",
    "GoogleServiceDisabled",
    "GoogleUncertain",
    "build_google_connector",
    "can_insert",
    "can_use_contacts",
    "can_use_tasks",
    "can_use_youtube",
    "connect_scopes",
    "google_tools_configured",
    "google_tools_startup_note",
    "grant_name",
    "held_grants",
    "never_sent",
    "register_tools_oauth",
]
