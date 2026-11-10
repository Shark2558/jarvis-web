# src/jarvis/api/r6_wiring.py
"""R6, the build book, on the app (docs/plans/r6-build-book.md "Seams the I0 adds" item 5 and
"I1"). Kept out of `api/app.py` so that file stays a short list of named steps, as R2's
`api/personal.py`, R3's `api/home_wiring.py` and R4's `api/r4_wiring.py` do.

The three slots in `api/app.py` (each one line):
- `await wire_r6(app, s, docs, audit)` in the lifespan, right after `wire_r4`. `audit` is the chain
  the gateway is built on. NOTE for I1: at this point `app.state.permissions` and
  `app.state.gateway` do not exist yet (`_wire_gateway` runs later); anything that needs them reads
  them from `request.app.state` when a request arrives, as `api/vault.py` does.
- `install_r6_routes(app)` in `_include_routers`, just before the console router.
- `install_show_lock(app, s)` in `_install_middleware` (Google sign-in only), just before
  `_install_google_sign_in`: Starlette wraps outward, so the guest lock then runs INSIDE the
  session middleware and can read the cookie session (D10).

R6 I0: stubs. `wire_r6` leaves every R6 part OFF (`R6_STATE` on `app.state`, all None), the routes
answer 503 `book_off`, the guest lock is not installed, there are no tick jobs and no privacy
sources. I1 fills them: `r6_tick_jobs` joins `_tick_jobs` and R5.1's watchdog list
(`check_job_names`), `r6_privacy_sources` joins `personal.privacy_sources`.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from jarvis.api.book import router as book_router
from jarvis.api.book_http import BookNoStore
from jarvis.api.book_show import router as book_show_router
from jarvis.config import Settings
from jarvis.storage.docs import Docs
from jarvis.ticks import TickJob
from jarvis.tools.audit import AuditTrail

# What I1 puts on app.state (each None while that part is off; routes read them per request):
R6_STATE: tuple[str, ...] = (
    "book_source",  # A: buildbook.release (BookSource)
    "book_vault",  # B: sealed releases (BookVault)
    "book_sealer",  # B: BookSealer.ensure + the book_seal tick job
    "book_sessions",  # C: BookSessions
    "book_lock",  # C: ShowLock, read by the guest-lock middleware on every request (D10)
    "book_talk",  # C: BookTalker
    "book_service",  # C: BookService (open / close / wipe / notice / sweep)
)


async def wire_r6(app: FastAPI, s: Settings, docs: Docs, audit: AuditTrail) -> None:
    """R6 I0 stub: every R6 part OFF. I1 builds them here (`_notifier(app)`, billing, brains,
    voice and this audit chain; permissions from `request.app.state` at request time)."""
    for attr in R6_STATE:
        setattr(app.state, attr, None)


def install_r6_routes(app: FastAPI) -> None:
    """`/v1/book/...` (B: api/book.py, C: api/book_show.py), every answer `no-store`."""
    app.add_middleware(BookNoStore)
    app.include_router(book_router)
    app.include_router(book_show_router)


def install_show_lock(app: FastAPI, s: Settings) -> None:
    """R6 I0 stub: no guest lock yet. Part C's `api/book_lock.ShowLockMiddleware` is added here
    at I1 (Google sign-in only), so it runs inside the session middleware."""
    return None


def r6_tick_jobs(app: FastAPI) -> tuple[TickJob, ...]:
    """R6 I0 stub: none. I1: `book_seal` (B) and `book_sweep` (C) on the existing tick."""
    return ()


def r6_privacy_sources(app: FastAPI) -> tuple[Any, ...]:
    """R6 I0 stub: none. I1: `book_sessions_source` and `book_sealed_source` (D16)."""
    return ()


__all__ = [
    "R6_STATE",
    "install_r6_routes",
    "install_show_lock",
    "r6_privacy_sources",
    "r6_tick_jobs",
    "wire_r6",
]
