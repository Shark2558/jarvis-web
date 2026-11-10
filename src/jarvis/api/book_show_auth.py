# src/jarvis/api/book_show_auth.py
"""Who the build book's show routes accept (R6 D10; integrated review SEC-4).

At a guest open the presenting browser's cookie session stops being an owner session: it becomes a
SHOW-ONLY marker `{book_show: {uid, iat}}` with no owner e-mail key (`make_show_only`). Only the
show routes (`/v1/book/show/*`, `POST /v1/book/close`), `GET /v1/book/show/lock` and `POST
/v1/book/resume` accept it (`require_show_auth` + `show_user`); `require_auth` never does, so a
cookie the guest copies out of DevTools opens nothing of the owner's, before or after Resume.

Resume and the emergency unlock record "sessions valid after" for the owners (`lock.py`, read with
the lock); `ShowLockMiddleware` clears every owner cookie and marker issued before it
(`cookie_owner` gives the session's owner and when it was issued). The browser that resumed is
`restamp`ed: an owner session again, issued at that mark, so it keeps working.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from jarvis.api.auth import (
    CSRF_HEADER,
    CSRF_VALUE,
    SAFE_METHODS,
    SESSION_ABSOLUTE_MAX_S,
    SESSION_EMAIL_KEY,
    SESSION_ISSUED_KEY,
    CSRFRejected,
    cookie_now,
    require_auth,
    session_email,
)
from jarvis.api.identity import current_user, user_id_for_email
from jarvis.config import AuthMode, Settings

SHOW_KEY = "book_show"  # the presenting browser's show-only marker {uid, iat}
GUEST_FLAG = "book_guest"  # set in the presenting browser's session at a guest open
_bearer = HTTPBearer(auto_error=False)


def _owner_email(s: Settings, uid: str) -> str | None:
    return next((e for e in s.owner_emails if user_id_for_email(e) == uid), None)


def show_marker(session: dict[str, Any], s: Settings) -> tuple[str, float] | None:
    """(owner id, issued) of a live show-only marker, or None."""
    if s.auth_mode is not AuthMode.GOOGLE:
        return None
    mark = session.get(SHOW_KEY)
    if not isinstance(mark, dict):
        return None
    uid, issued = mark.get("uid"), mark.get("iat")
    if not isinstance(uid, str) or not isinstance(issued, int | float):
        return None
    if cookie_now() - issued > SESSION_ABSOLUTE_MAX_S or _owner_email(s, uid) is None:
        return None
    return uid, float(issued)


def cookie_owner(request: Request, s: Settings) -> tuple[str, float] | None:
    """(owner id, issued) of this cookie session: an owner's sign-in or a show-only marker."""
    if "session" not in request.scope:
        return None
    email = session_email(request, s)
    if email is not None:
        return user_id_for_email(email), float(request.session[SESSION_ISSUED_KEY])
    return show_marker(request.session, s)


def make_show_only(session: dict[str, Any], uid: str) -> None:
    """At a guest open: nothing of the owner's sign-in stays in the presenting browser."""
    issued = session.get(SESSION_ISSUED_KEY, cookie_now())
    session.clear()
    session[SHOW_KEY] = {"uid": uid, "iat": issued}
    session[GUEST_FLAG] = True  # held at once on every instance (book_lock.py)


def restamp(session: dict[str, Any], s: Settings, uid: str, at: float) -> None:
    """The browser that resumed: an owner session again, issued at the Resume mark."""
    email = _owner_email(s, uid)
    session.clear()
    if email is not None:
        session[SESSION_EMAIL_KEY] = email
        session[SESSION_ISSUED_KEY] = at


async def require_show_auth(
    request: Request, creds: HTTPAuthorizationCredentials | None = Depends(_bearer)
) -> None:
    """`require_auth`, or the show-only marker (with the CSRF header on writes)."""
    s: Settings = request.app.state.settings
    if "session" in request.scope and show_marker(request.session, s) is not None:
        if request.method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
            raise CSRFRejected()
        return
    await require_auth(request, creds, s)


def by_show_marker(request: Request) -> bool:
    """True when this request comes from a show-only marker, not an owner sign-in or a token."""
    s: Settings = request.app.state.settings
    if "session" not in request.scope or session_email(request, s) is not None:
        return False
    return show_marker(request.session, s) is not None


def show_user(request: Request) -> str:
    """The owner a show route acts for: the marker's, else `current_user`'s."""
    s: Settings = request.app.state.settings
    if "session" in request.scope and (mark := show_marker(request.session, s)) is not None:
        return mark[0]
    return current_user(request)


__all__ = [
    "GUEST_FLAG",
    "SHOW_KEY",
    "by_show_marker",
    "cookie_owner",
    "make_show_only",
    "require_show_auth",
    "restamp",
    "show_marker",
    "show_user",
]
