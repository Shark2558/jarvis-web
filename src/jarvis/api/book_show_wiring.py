# src/jarvis/api/book_show_wiring.py
"""Builder C's parts on the app, in one call for I1's `wire_r6` (R6 "I1"; this file is C's, the
wiring files stay I1's). `wire_book_c(app, s, docs, audit, source=..., keyring=..., prefs=...)`
puts on `app.state`:

    book_sessions     buildbook.sessions.DocBookSessions   (Settings book_session_minutes,
                                                            book_idle_minutes, book_talk_questions)
    book_lock         buildbook.lock.DocShowLock           (read by ShowLockMiddleware)
    book_talk         buildbook.talk.BookTalk              (app.state.brains, billing, brain_mode)
    book_service      buildbook.service.BookService        (the routes' entry point)
    book_show_limits  per-owner / per-session rate limits of the show routes

Without a keyring (no JARVIS_TOKEN_KEY) or a book source, all of them are None and every route
answers 503 book_off (D6: no keyring -> book OFF). It runs after wire_r4 and BEFORE the gateway
and the permissions exist: the open/resume routes read `app.state.permissions` per request.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import FastAPI

from jarvis.api.r4_wiring import _notifier
from jarvis.api.ratelimit import RateLimiter
from jarvis.buildbook.lock import DocShowLock
from jarvis.buildbook.ports import BookSource
from jarvis.buildbook.service import BookService, BookSweepJob
from jarvis.buildbook.sessions import DocBookSessions
from jarvis.buildbook.show_script import Prefs
from jarvis.buildbook.talk import BookTalk
from jarvis.config import Settings
from jarvis.keyring import Keyring
from jarvis.notify.ports import Notifier
from jarvis.storage.docs import Docs
from jarvis.tools.audit import AuditTrail

C_STATE = ("book_sessions", "book_lock", "book_talk", "book_service", "book_show_limits")
LIMITS = {  # per minute; `ask` is per session (D12: 6 a minute), the rest per owner
    "open": 5,  # D8
    "script": 20,
    "speak": 90,  # ~100 beats a show, one prefetched
    "hear": 10,
    "ask": 6,
    "beat": 10,  # the show beats every 60 s
    "close": 10,
    "resume": 10,
}


def _spend(app: FastAPI) -> Any:
    async def spend(uid: str) -> Mapping[str, Any]:
        usage = await app.state.billing.usage(uid)
        return {"month_inr": usage.used_inr, "limit_inr": usage.limit_inr}

    return spend


def _parts(
    app: FastAPI,
    s: Settings,
    docs: Docs,
    keyring: Keyring,
    source: BookSource,
    prefs: Prefs | None,
) -> tuple[DocBookSessions, DocShowLock, BookTalk]:
    sessions = DocBookSessions(
        docs,
        keyring,
        prefix=s.firestore_prefix,
        session_minutes=s.book_session_minutes,
        idle_minutes=s.book_idle_minutes,
        questions=s.book_talk_questions,
    )
    talk = BookTalk(
        app.state.brains,
        app.state.billing,
        app.state.brain_mode,
        source,
        sessions,
        prefs=prefs,
        owner_emails=tuple(s.owner_emails),
    )
    return sessions, DocShowLock(docs, prefix=s.firestore_prefix), talk


def wire_book_c(
    app: FastAPI,
    s: Settings,
    docs: Docs,
    audit: AuditTrail,
    *,
    source: BookSource | None,
    keyring: Keyring | None,
    prefs: Prefs | None = None,
    notifier: Notifier | None = None,
    on_close: Callable[[str], Awaitable[None]] | None = None,
) -> BookService | None:
    for name in C_STATE:
        setattr(app.state, name, None)
    if keyring is None or source is None:
        return None
    sessions, lock, talk = _parts(app, s, docs, keyring, source, prefs)
    p = s.firestore_prefix
    service = BookService(
        source=source,
        sessions=sessions,
        lock=lock,
        talk=talk,
        audit=audit,
        notifier=notifier or _notifier(app),
        docs=docs,
        prefix=p,
        honorific=s.user_honorific,
        timezone=s.user_timezone,
        prefs=prefs,
        spend=_spend(app),
        owner_emails=tuple(s.owner_emails),
        on_close=on_close,
    )
    app.state.book_sessions, app.state.book_lock = sessions, lock
    app.state.book_talk, app.state.book_service = talk, service
    app.state.book_show_limits = {k: RateLimiter(v) for k, v in LIMITS.items()}
    return service


def book_sweep_job(app: FastAPI) -> BookSweepJob | None:
    """D14's `book_sweep` TickJob for I1's `r6_tick_jobs` (None while the book is off)."""
    svc: BookService | None = getattr(app.state, "book_service", None)
    return None if svc is None else BookSweepJob(svc)


__all__ = ["C_STATE", "LIMITS", "book_sweep_job", "wire_book_c"]
