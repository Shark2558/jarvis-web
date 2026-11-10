# src/jarvis/api/r6_wiring.py
"""R6: the build book on the app (plan docs/plans/r6-build-book.md "Seams the I0 adds" 5, "I1").
Kept out of `api/app.py` so that file stays a short list of named steps, as R4's
`api/r4_wiring.py` does. app.py calls exactly three things from here:

- `wire_r6` (lifespan, right after `wire_r4`, BEFORE the gateway and the permissions service are
  built: read those live from `app.state` when a request runs, as home_wiring's
  `_LivePermissions` does). I0: every R6 state attribute is None (the book is OFF). I1: the book
  source, vault + sealer (B), sessions, lock, talk and service (C) on `_notifier(app)`, billing,
  the brains, voice and the gateway's audit chain.
- `install_r6_routes` (before the console router): /v1/book (api/book.py, B) and the session and
  show routes (api/book_show.py, C). `GET /book/show` is the console's (api/console.py).
- `install_show_lock(app, s)` (Google sign-in only, called just BEFORE the session middleware is
  added, so the lock runs INSIDE `SessionMiddleware` and can read the cookie session; Starlette:
  the last added is the outermost; tests/test_r6_wiring_seams.py pins the order). I0: adds
  nothing. I1: `api/book_lock.py::ShowLockMiddleware` reading `app.state.book_lock` per request.

And `r6_tick_jobs(app)`: the `book_seal` and `book_sweep` TickJobs (I1 adds them to the tick and to
R5.1's 5-minute watchdog list; `check_job_names` keeps names unique). I0: none.
"""

from __future__ import annotations

from fastapi import FastAPI

from jarvis.api.book import install_book
from jarvis.api.book_show import install_book_show
from jarvis.config import Settings
from jarvis.storage.docs import Docs
from jarvis.ticks import TickJob
from jarvis.tools.audit import AuditTrail

# what wire_r6 puts on app.state (None = off): I1 fills them; the routes read them per request
R6_STATE = (
    "book_source",  # A: buildbook/release.py (ports.BookSource)
    "book_vault",  # B: buildbook/seal.py (ports.BookVault)
    "book_sealer",  # B: buildbook/sealer.py (BookSealer.ensure)
    "book_sessions",  # C: buildbook/sessions.py (ports.BookSessions)
    "book_lock",  # C: buildbook/lock.py (ports.ShowLock; the middleware's store)
    "book_talk",  # C: buildbook/talk.py (ports.BookTalker)
    "book_service",  # C: buildbook/service.py (open, close, wipe, notice, sweep)
)
R6_JOB_NAMES = frozenset({"book_seal", "book_sweep"})


async def wire_r6(app: FastAPI, s: Settings, docs: Docs, audit: AuditTrail) -> None:
    """Everything R6 on `app.state` (None when off), after R4 and before the gateway."""
    for name in R6_STATE:
        setattr(app.state, name, None)


def install_r6_routes(app: FastAPI) -> None:
    """Every Contract route, authed and no-store (I0: each answers 503 book_off)."""
    install_book(app)
    install_book_show(app)


def install_show_lock(app: FastAPI, s: Settings) -> None:
    """D10's guest lock over every cookie session of the owner. I0: nothing yet."""
    return None


def r6_tick_jobs(app: FastAPI) -> tuple[TickJob, ...]:
    """D7 `book_seal` and D14 `book_sweep` on the existing tick (no new Scheduler job). I0: none."""
    return ()


__all__ = [
    "R6_JOB_NAMES",
    "R6_STATE",
    "install_r6_routes",
    "install_show_lock",
    "r6_tick_jobs",
    "wire_r6",
]
