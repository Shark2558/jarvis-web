# src/jarvis/api/book_gate.py
"""The gate every build book owner route passes (R6 D8, D9; "Contract"; builder B), kept out of
api/book.py: the refusal answered as `{error, detail}` + no-store (`BookRefused`, handled by
`api.book.install_book`), the parts read from `app.state` per request (missing -> 503 book_off),
console only (a bearer script -> 403 console_only), the per-owner rate limits, and the live OWNER
book session a ● token opens. That session is resolved through C's `app.state.book_service`
when it is wired, so a session that has just expired or gone idle is FINISHED there (D14: audit
`book_close`, the `book_session_closed` notice) before the route answers 401; without the
service, through `app.state.book_sessions`. A store that breaks answers 503 unavailable; nothing
here logs a token.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import Request

from jarvis.api.auth import session_email
from jarvis.api.book_http import BOOK_OFF
from jarvis.buildbook.model import SessionView
from jarvis.buildbook.ports import SessionGone
from jarvis.config import AuthMode, Settings
from jarvis.logging import get_logger

log = get_logger(__name__)

TOKEN_MAX = 128
GONE = "Open the build book again."
UNAVAILABLE = "The build book can't be reached right now."


class BookRefused(Exception):
    """A route's refusal: answered as {error, detail} with no-store by `install_book`."""

    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def need(request: Request, name: str) -> Any:
    part = getattr(request.app.state, name, None)
    if part is None:
        raise BookRefused(503, "book_off", BOOK_OFF)
    return part


def console_only(request: Request) -> None:
    """The book opens in the console only: a signed-in browser (or token-mode dev)."""
    s: Settings = request.app.state.settings
    if session_email(request, s) is not None or (s.auth_mode is AuthMode.TOKEN and s.env == "dev"):
        return
    raise BookRefused(
        403, "console_only", "The build book opens only in the JARVIS console, not from a script."
    )


def limit(request: Request, name: str, uid: str) -> None:
    allowed, _ = request.app.state.book_limits[name].allow(uid)
    if not allowed:
        raise BookRefused(429, "rate_limited", "Too many requests; wait a moment.")


def _resolver(request: Request) -> Any:
    """C's BookService.resolve when wired (it finishes a session that just ended: D14 audit and
    notice), else the sessions store's own (I1 wires the service; tests may wire neither)."""
    sessions = need(request, "book_sessions")
    service = getattr(request.app.state, "book_service", None)
    return getattr(service, "resolve", None) or sessions.resolve


async def owner_session(request: Request, uid: str, token: str | None) -> SessionView:
    """The live OWNER book session this token opens (D9: sections, older books, the code)."""
    resolve = _resolver(request)
    if not token or len(token) > TOKEN_MAX:
        raise BookRefused(401, "session_gone", GONE)
    try:
        session: SessionView = await resolve(uid, token, now=now())
    except SessionGone:
        raise BookRefused(401, "session_gone", GONE) from None
    except Exception as exc:  # noqa: BLE001 - a store outage: fail closed, plain words
        log.error("book session unreadable", extra={"error": type(exc).__name__})
        raise BookRefused(503, "unavailable", UNAVAILABLE) from None
    if session.audience != "owner":
        raise BookRefused(403, "owner_only", "Only your own book session opens this.")
    return session


__all__ = [
    "GONE",
    "TOKEN_MAX",
    "UNAVAILABLE",
    "BookRefused",
    "console_only",
    "limit",
    "need",
    "now",
    "owner_session",
]
