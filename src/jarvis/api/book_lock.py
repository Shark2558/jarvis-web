# src/jarvis/api/book_lock.py
"""The guest lock over the owner's consoles (R6 D10; cross-cutting security, Layer 1).

`ShowLockMiddleware` is pure ASGI and sits INSIDE `SessionMiddleware` (I1: `install_show_lock(app,
s)` calls `install_show_lock_middleware`, just before the session middleware is added; Google
sign-in only). For a request carrying an owner's cookie session it reads the lock store from
`request.app.state.book_lock` (`ports.ShowLock`, cached <= 3 s per instance) and, while ANY
owner's guest lock is on, lets through only:

    GET  /book/show, /static/..., /health, /console/config, /auth/login, /auth/callback
    POST /auth/logout
    GET  /v1/book/show/script · POST /v1/book/show/{speak,hear,ask,beat}
    POST /v1/book/close, /v1/book/resume, /v1/passkeys/challenge
    POST /v1/passkeys/reset   (plan "Risks": a passkey lost mid-show must stay recoverable; the
                               route itself still wants a Google sign-in from the last 5 minutes,
                               which a guest can't make, and a guest open consumes the owner's)

`GET /` -> 302 /book/show; everything else, `/auth/me` included -> 423 {error: show_locked,
detail, lock_id?} (`lock_id` only for the owner whose lock it is: the target of his
`book_resume` passkey check). Unreadable lock -> 503 show_lock_unreadable for everything but the
allowed routes. Bearer callers, the Scheduler, Telegram and the home bridge carry no cookie
session and are untouched. A lock on ANY owner holds every owner's sessions, so switching to the
other owner's Google account in the same browser is no way out.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from jarvis.api.auth import session_email
from jarvis.api.book_http import NO_STORE
from jarvis.api.identity import user_id_for_email
from jarvis.buildbook.lines import LINES
from jarvis.buildbook.model import ShowLockState
from jarvis.buildbook.ports import LockUnreadable, ShowLock
from jarvis.config import Settings

SHOW_PAGE = "/book/show"
ALLOWED: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", SHOW_PAGE),
        ("GET", "/health"),
        ("GET", "/console/config"),
        ("GET", "/auth/login"),
        ("GET", "/auth/callback"),
        ("POST", "/auth/logout"),
        ("GET", "/v1/book/show/script"),
        ("POST", "/v1/book/show/speak"),
        ("POST", "/v1/book/show/hear"),
        ("POST", "/v1/book/show/ask"),
        ("POST", "/v1/book/show/beat"),
        ("POST", "/v1/book/close"),
        ("POST", "/v1/book/resume"),
        ("POST", "/v1/passkeys/challenge"),
        ("POST", "/v1/passkeys/reset"),
    }
)
_STATIC = re.compile(r"/static/[A-Za-z0-9._\-]+(?:/[A-Za-z0-9._\-]+){0,2}")
LOCKED = "A guest is watching the build book. " + LINES["hand_back"]
UNREADABLE = "JARVIS can't tell whether a guest show is running. Try again in a moment."
GUEST_FLAG = "book_guest"  # set in the presenting browser's session at a guest open


def allowed(method: str, path: str) -> bool:
    """Whether a request may pass while a guest lock is on (exact method and path)."""
    verb = "GET" if method == "HEAD" else method
    if (verb, path) in ALLOWED:
        return True
    return verb == "GET" and ".." not in path and _STATIC.fullmatch(path) is not None


def _json(status: int, body: dict[str, Any]) -> Response:
    return JSONResponse(status_code=status, content=body, headers=NO_STORE)


class ShowLockMiddleware:
    """Pure ASGI: reads the cookie session (already decoded by SessionMiddleware) and the lock."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self._s = settings
        self._owners = tuple(dict.fromkeys(user_id_for_email(e) for e in settings.owner_emails))

    async def _lock_on(
        self, store: ShowLock, uid: str, session: dict[str, Any]
    ) -> tuple[ShowLockState | None, bool]:
        """(a lock that holds this session, whether it is this owner's own). The presenting
        browser carries GUEST_FLAG: for it an "unlocked" from the <= 3 s cache is read again
        uncached, so no other instance's stale cache lets it out right after the open; a flag
        the store no longer confirms (the lock was lifted elsewhere) clears itself."""
        own = await store.get(uid)
        refresh = getattr(store, "refresh", None)
        if own is None and session.get(GUEST_FLAG) and callable(refresh):
            own = await refresh(uid)
            if own is None:
                session.pop(GUEST_FLAG, None)
        if own is not None:
            return own, True
        for other in self._owners:
            if other != uid and (state := await store.get(other)) is not None:
                return state, False
        return None, False

    def _answer(self, scope: Scope, state: ShowLockState, own: bool) -> Response:
        if scope["path"] == "/" and scope["method"] in ("GET", "HEAD"):
            return RedirectResponse(SHOW_PAGE, status_code=302, headers=NO_STORE)
        body: dict[str, Any] = {"error": "show_locked", "detail": LOCKED}
        if own:
            body["lock_id"] = state.id
        return _json(423, body)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or "session" not in scope:
            await self.app(scope, receive, send)
            return
        if allowed(scope["method"], scope["path"]):
            await self.app(scope, receive, send)
            return
        email = session_email(Request(scope), self._s)
        store: ShowLock | None = getattr(scope["app"].state, "book_lock", None)
        if email is None or store is None:
            await self.app(scope, receive, send)
            return
        try:
            state, own = await self._lock_on(store, user_id_for_email(email), scope["session"])
        except LockUnreadable:
            await _json(503, {"error": "show_lock_unreadable", "detail": UNREADABLE})(
                scope, receive, send
            )
            return
        if state is None:
            await self.app(scope, receive, send)
            return
        await self._answer(scope, state, own)(scope, receive, send)


def install_show_lock_middleware(app: FastAPI, s: Settings) -> None:
    """What I1's `r6_wiring.install_show_lock` does (Google sign-in only; called just before the
    session middleware is added, so this runs INSIDE it)."""
    app.add_middleware(ShowLockMiddleware, settings=s)


__all__ = [
    "ALLOWED",
    "GUEST_FLAG",
    "LOCKED",
    "ShowLockMiddleware",
    "allowed",
    "install_show_lock_middleware",
]
