# src/jarvis/api/integrations.py
"""Linking the owner's Google account for the Calendar + Gmail tools (Layer 1 → 6).

GET  /connect/google                 signed-in owner → Google consent (offline, PKCE, login_hint);
                                     ?add=<tasks|contacts|youtube> (Integrations → Grant; exactly
                                     one allow-listed name) also asks for that optional scope; a
                                     renewal asks again for every optional scope the link holds
GET  /connect/google/callback        store tokens iff the consenting account IS the signed-in owner
                                     AND every tool scope was granted; failures redirect to
                                     /?connect_error=<code> (browser landing); a grant from the
                                     wrong account is revoked at Google (best effort)
GET  /v1/integrations          {google: {connected, email, scopes, expires_at, needs_reconnect,
                                         tasks_granted, contacts_granted, youtube_granted,
                                         tasks_available, contacts_available,
                                         youtube_available}}
                                         (the three Grants are optional; review C7: a Grant
                                         is "available" — its row offered — only when its tools
                                         exist on this server (YouTube: the server's API key)
                                         and its permission row is not Never),
                                drive_available, maps_available}
                                         (final review: Drive is on here — JARVIS_DRIVE — and
                                         Maps has the server's key, and the row is not Never;
                                         false → the console hides Drive / Home and Work. Each
                                         still reads its own endpoint, D7)
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
from jarvis.api.rows import DRIVE_TOOL, MAPS_TOOL, switched_off
from jarvis.config import Settings
from jarvis.integrations.google import (
    GRANTS,
    GoogleConnector,
    GoogleScopesMissing,
    can_use_contacts,
    can_use_tasks,
    can_use_youtube,
    connect_scopes,
    grant_name,
    held_grants,
)
from jarvis.logging import get_logger

log = get_logger(__name__)

router = APIRouter()
CONNECT_OWNER_KEY = "google_connect_owner"  # session: who started the consent flow
# Review C7 (D8): the tool each Grant unlocks, so "Never" on its permission row (To-do list,
# Contacts, YouTube) hides the Grant row; decided by the owner's own rules, as the gateway would.
GRANT_TOOLS: dict[str, str] = {
    "tasks": "tasks_list",
    "contacts": "contacts_search",
    "youtube": "youtube_my_playlists",
}
# Final review (D8): the features with their own endpoints whose sections "Never" hides.
FEATURE_TOOLS: dict[str, str] = {"drive": DRIVE_TOOL, "maps": MAPS_TOOL}


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
    google = _google(request)
    email = session_email(request, s)
    if email is None:  # a browser session only: scripts have no consent screen
        raise HTTPException(401, "sign in required")
    request.session[CONNECT_OWNER_KEY] = email
    # An optional scope only when asked for (Integrations → Grant: ?add=<one allow-listed name>,
    # exactly once) or already held by the link being renewed; a plain reconnect asks for what it
    # always did plus what the link holds (review L8; slice 12 D7).
    held = await google.status(user_id_for_email(email))
    grants = set(held_grants(held["scopes"])) if held["connected"] else set()
    added = request.query_params.getlist("add")
    if len(added) == 1 and (name := grant_name(added[0])) is not None:
        grants.add(name)
    return await request.app.state.oauth.google_tools.authorize_redirect(
        request,
        _callback_url(s),
        scope=connect_scopes(grants),
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
    # slice 10 C: the optional to-do list scope; false → the console offers "Grant"
    tasks_granted: bool = False
    # slice 12 D7: the optional contacts / YouTube playlists scopes, the same way
    contacts_granted: bool = False
    youtube_granted: bool = False
    # review C7: false → the console offers no Grant row (no tools here, or the row is Never)
    tasks_available: bool = True
    contacts_available: bool = True
    youtube_available: bool = False


class Integrations(BaseModel):
    google: GoogleStatus
    # final review: false → the console hides Integrations → Google Drive / Maps' Home and Work
    drive_available: bool = False
    maps_available: bool = False


@router.get("/v1/integrations", response_model=Integrations, dependencies=[Depends(require_auth)])
async def integrations(
    request: Request,
    google: GoogleConnector = Depends(_google),
    uid: str = Depends(current_user),
) -> Integrations:
    st = await google.status(uid)
    linked, scopes = bool(st["connected"]), st["scopes"]
    # a Never row is decided as the gateway would (`api.rows`); unreadable rules: offered
    off = await switched_off(request, uid, {**GRANT_TOOLS, **FEATURE_TOOLS})
    # YouTube's (and Maps') tools exist exactly when Maps + YouTube are set up here
    # (app.state.media: the server's API key, `jarvis.media.service.build_media`); Drive's when
    # JARVIS_DRIVE is on (app.state.drive)
    media = getattr(request.app.state, "media", None)
    drive = getattr(request.app.state, "drive", None)
    here = {"tasks": True, "contacts": True, "youtube": media is not None}
    available = {name: here[name] and name not in off for name in GRANTS}
    return Integrations(
        drive_available=drive is not None and "drive" not in off,
        maps_available=media is not None and "maps" not in off,
        google=GoogleStatus(
            **st,
            tasks_granted=linked and can_use_tasks(scopes),
            contacts_granted=linked and can_use_contacts(scopes),
            youtube_granted=linked and can_use_youtube(scopes),
            tasks_available=available["tasks"],
            contacts_available=available["contacts"],
            youtube_available=available["youtube"],
        ),
    )


@router.post("/v1/integrations/google/disconnect", dependencies=[Depends(require_auth)])
async def disconnect(
    google: GoogleConnector = Depends(_google), uid: str = Depends(current_user)
) -> dict[str, Any]:
    await google.disconnect(uid)
    return {"ok": True, "google": {"connected": False}}
