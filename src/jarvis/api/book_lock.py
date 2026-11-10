# src/jarvis/api/book_lock.py
"""The guest lock over the owner's consoles (R6 D10; cross-cutting security, Layer 1).

`ShowLockMiddleware` is pure ASGI and sits INSIDE `SessionMiddleware` (I1: `install_show_lock(app,
s)` calls `install_show_lock_middleware`, just before the session middleware is added; Google
sign-in only). For a request carrying an owner's cookie session it reads the lock store from
`request.app.state.book_lock` (`ports.ShowLock`, cached <= 3 s per instance) and, while ANY
owner's guest lock is on, lets through only:

    GET  /book/show, /static/..., /health, /console/config, /auth/login, /auth/callback
    POST /auth/logout
    GET  /v1/book/show/script, /v1/book/show/lock · POST /v1/book/show/{speak,hear,ask,beat}
    POST /v1/book/close, /v1/book/resume, /v1/passkeys/challenge

Every passkey register / reset / cancel / remove route is locked: a guest can make a "fresh"
Google sign-in in this browser with one click (Google returns no `auth_time` unless asked), so
nothing a sign-in unlocks may be reachable here. A sign-in made under the lock (`/auth/login`,
`/auth/callback`) gives a session this middleware holds like any other; it lifts nothing. A
passkey lost mid-show is recovered with the owner-only emergency unlock (`python -m
jarvis.buildbook.unlock`, server credentials), never through the browser.

A websocket of an owner's cookie session is closed (4423 locked, 4503 unreadable) while a lock
is on: never silently exempt. An HTTP or websocket scope with no `session` in Google mode means
the middleware was installed outside SessionMiddleware: 503 (fail closed, logged), never "pass".

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
from jarvis.config import AuthMode, Settings
from jarvis.logging import get_logger

log = get_logger(__name__)

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
        ("GET", "/v1/book/show/lock"),  # I1: the show learns the lock (and its id) without a token
        ("POST", "/v1/book/show/speak"),
        ("POST", "/v1/book/show/hear"),
        ("POST", "/v1/book/show/ask"),
        ("POST", "/v1/book/show/beat"),
        ("POST", "/v1/book/close"),
        ("POST", "/v1/book/resume"),
        ("POST", "/v1/passkeys/challenge"),
    }
)
_STATIC = re.compile(r"/static/[A-Za-z0-9._\-]+(?:/[A-Za-z0-9._\-]+){0,2}")
LOCKED = "A guest is watching the build book. " + LINES["hand_back"]
UNREADABLE = "JARVIS can't tell whether a guest show is running. Try again in a moment."
UNWIRED = "The guest lock isn't installed where it can see sign-ins, so JARVIS stays closed."
WS_LOCKED, WS_UNREADABLE = 4423, 4503
GUEST_FLAG = "book_guest"  # set in the presenting browser's session at a guest open


def allowed(method: str, path: str) -> bool:
    """Whether a request may pass while a guest lock is on (exact method and path)."""
    verb = "GET" if method == "HEAD" else method
    if (verb, path) in ALLOWED:
        return True
    return verb == "GET" and ".." not in path and _STATIC.fullmatch(path) is not None


async def lock_for(
    store: ShowLock, owners: tuple[str, ...], uid: str
) -> tuple[ShowLockState | None, bool]:
    """(the lock holding `uid`'s consoles, whether it is his own): a lock on ANY owner holds
    every owner's sessions; only his own can be lifted by him. LockUnreadable propagates."""
    if (own := await store.get(uid)) is not None:
        return own, True
    for other in owners:
        if other != uid and (state := await store.get(other)) is not None:
            return state, False
    return None, False


def owner_ids(s: Settings) -> tuple[str, ...]:
    return tuple(dict.fromkeys(user_id_for_email(e) for e in s.owner_emails))


def _json(status: int, body: dict[str, Any]) -> Response:
    return JSONResponse(status_code=status, content=body, headers=NO_STORE)


class ShowLockMiddleware:
    """Pure ASGI: reads the cookie session (already decoded by SessionMiddleware) and the lock."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self._s = settings
        self._owners = owner_ids(settings)

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
        return await lock_for(store, self._owners, uid)

    def _answer(self, scope: Scope, state: ShowLockState, own: bool) -> Response:
        if scope["path"] == "/" and scope["method"] in ("GET", "HEAD"):
            return RedirectResponse(SHOW_PAGE, status_code=302, headers=NO_STORE)
        body: dict[str, Any] = {"error": "show_locked", "detail": LOCKED}
        if own:
            body["lock_id"] = state.id
        return _json(423, body)

    async def _held(self, scope: Scope) -> tuple[ShowLockState | None, bool]:
        """(the lock holding this cookie session, whether it is the owner's own); LockUnreadable
        propagates, and so does a Google app with no lock store to read (SEC-3: I1 always
        builds one, so a missing store is never read as "unlocked"). Not an owner's session, or
        no store outside Google mode: (None, False)."""
        view = scope if scope["type"] == "http" else {**scope, "type": "http"}  # same session dict
        email = session_email(Request(view), self._s)
        store: ShowLock | None = getattr(scope["app"].state, "book_lock", None)
        if email is None:
            return None, False
        if store is None:
            if self._s.auth_mode is AuthMode.GOOGLE:
                log.error("the show lock has no lock store to read")
                raise LockUnreadable(UNREADABLE)
            return None, False
        return await self._lock_on(store, user_id_for_email(email), scope["session"])

    async def _websocket(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            state, _ = await self._held(scope)
        except LockUnreadable:
            await send({"type": "websocket.close", "code": WS_UNREADABLE})
            return
        if state is not None:
            await send({"type": "websocket.close", "code": WS_LOCKED})
            return
        await self.app(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)  # lifespan
            return
        if "session" not in scope:
            if self._s.auth_mode is not AuthMode.GOOGLE:
                await self.app(scope, receive, send)
                return
            log.error("the show lock sees no session: installed outside SessionMiddleware")
            await _json(503, {"error": "show_lock_unwired", "detail": UNWIRED})(
                scope, receive, send
            )
            return
        if scope["type"] == "websocket":
            await self._websocket(scope, receive, send)
            return
        if allowed(scope["method"], scope["path"]):
            await self.app(scope, receive, send)
            return
        try:
            state, own = await self._held(scope)
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
    "UNREADABLE",
    "ShowLockMiddleware",
    "allowed",
    "install_show_lock_middleware",
    "lock_for",
    "owner_ids",
]
