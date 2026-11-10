# src/jarvis/api/r6_wiring.py
"""R6: the build book on the app (plan docs/plans/r6-build-book.md "I1"). Kept out of `api/app.py`
so that file stays a short list of named steps, as R4's `api/r4_wiring.py` does. app.py calls:

- `wire_r6` (lifespan, right after `wire_r4`, BEFORE the gateway and the permissions service are
  built: the routes read those live from `app.state` per request). With the server's keyring it
  puts on `app.state`: A's `book_source` (`release.default_source()`), B's `book_vault`,
  `book_sealer`, `book_tickets` and `book_settings`, then C's `book_sessions`, `book_lock`,
  `book_talk`, `book_service` and `book_show_limits` (`wire_book_c`). No keyring -> all None and
  every route answers 503 book_off, except `GET /v1/book`, which says why (D6). Building them does
  no I/O: nothing is sealed at start-up (D7: a candidate that never goes live seals nothing).
  The guest lock is a stored document that outlives a revision and needs no keyring, so in Google
  mode `book_lock` is ALWAYS a `DocShowLock` (integrated review SEC-3): with no keyring and when
  R6's setup fails, the lock still holds and Resume answers 503 (the emergency unlock is the way
  out). `app.state.book_off` says why the book is off: "no_key", "setup_failed" or None (on).
- `install_r6_routes` (before the console router): /v1/book (api/book.py, B) and the session and
  show routes (api/book_show.py, C). `GET /book/show` is the console's (api/console.py).
- `install_show_lock(app, s)` (Google sign-in only, called just BEFORE the session middleware is
  added, so the lock runs INSIDE `SessionMiddleware` and can read the cookie session): C's
  `ShowLockMiddleware`, reading `app.state.book_lock` per request (D10).
- `r6_tick_jobs(app)`: B's `book_seal` and C's `book_sweep`, built once and shared by the tick and
  R5.1's 5-minute home watchdog (both idempotent; `home/watchdog.py` keeps them advisory).
- `r6_privacy_sources(app)`: D16's rows (B's `book_sealed`, `book_sessions` whose delete is C's
  wipe, `book_settings`), registered before Faces (which stays last).

One name for each Book setting across B (the store and `PUT /v1/book/settings`), C (`Prefs`) and
D (the reader's switches): `SETTINGS_KEYS` (`talk_on`, as the Contract's `talk: {on}`).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any

from fastapi import FastAPI

from jarvis.api.book import install_book
from jarvis.api.book_http import book_now
from jarvis.api.book_lock import install_show_lock_middleware, owner_ids
from jarvis.api.book_show import install_book_show
from jarvis.api.book_show_wiring import C_STATE, book_sweep_job, wire_book_c
from jarvis.api.identity import primary_user_id
from jarvis.api.r4_wiring import _notifier
from jarvis.buildbook.lock import DocShowLock
from jarvis.buildbook.owner import BookSettingsStore, BookTickets
from jarvis.buildbook.ports import BookSource
from jarvis.buildbook.privacy import BookSealedSource, BookSessionsSource, BookSettingsSource
from jarvis.buildbook.release import default_source
from jarvis.buildbook.seal import DocsBookVault
from jarvis.buildbook.sealer import BookSealer, BookSealJob
from jarvis.buildbook.service import BookService
from jarvis.buildbook.show_script import Prefs
from jarvis.config import AuthMode, Settings
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.notify.ports import Notifier
from jarvis.privacy.ports import PrivacySource
from jarvis.storage.docs import Docs
from jarvis.ticks import TickJob
from jarvis.tools.audit import AuditTrail

log = get_logger(__name__)

# what wire_r6 puts on app.state (None = off); the routes and the middleware read them per request
R6_STATE = (
    "book_source",  # A: buildbook/release.py (ports.BookSource)
    "book_vault",  # B: buildbook/seal.py (ports.BookVault)
    "book_sealer",  # B: buildbook/sealer.py (BookSealer.ensure)
    "book_tickets",  # B: buildbook/owner.py (the code download's single-use tickets)
    "book_settings",  # B: buildbook/owner.py (D16 Book settings)
    *C_STATE,  # C: sessions, lock (the middleware's store), talk, service, show_limits
)
R6_JOB_NAMES = frozenset({"book_seal", "book_sweep"})
SETTINGS_KEYS = ("creator_name", "show_voice", "talk_on", "allow_training_brain")
BOOK_OFF_NOTE = (
    "The build book is OFF: no encryption key on this server (it is sealed in the vault)"
)


class SettingsPrefs:
    """C's Book settings reader (`show_script.Prefs`) over B's store: the same four keys, the safe
    defaults when nothing is stored or it can't be read (never a training brain)."""

    def __init__(self, store: BookSettingsStore) -> None:
        self._store = store

    async def get(self, uid: str) -> Mapping[str, Any]:
        got = await self._store.get_or_default(uid)
        return got.model_dump(include=set(SETTINGS_KEYS))


def book_clock(app: FastAPI) -> Callable[[], datetime]:
    """`book_now` as a clock for the parts built once (tickets, the privacy row, L3)."""
    return lambda: book_now(app)


def lock_store(s: Settings, docs: Docs) -> DocShowLock:
    """D10's lock store: documents only, no keyring (it must hold while the book is off); it
    knows every owner, whose cookie sessions a Resume ends too (SEC-4)."""
    return DocShowLock(docs, prefix=s.firestore_prefix, owners=owner_ids(s))


def _book_off(app: FastAPI, s: Settings, lock: DocShowLock, why: str) -> None:
    """Every R6 part None, except the lock store in Google mode (SEC-3), and the reason."""
    st = app.state
    for name in R6_STATE:
        setattr(st, name, None)
    st.book_jobs = None
    st.book_lock = lock if s.auth_mode is AuthMode.GOOGLE else None
    st.book_off, st.book_off_error = why, None


def wire_book(
    app: FastAPI,
    s: Settings,
    docs: Docs,
    audit: AuditTrail,
    *,
    source: BookSource,
    keyring: Keyring | None,
    notifier: Notifier | None = None,
    prefs: Prefs | None = None,
    lock: DocShowLock | None = None,
) -> None:
    """A's source, B's vault/sealer/tickets/settings and C's parts on `app.state`, or all None
    (but the lock store in Google mode)."""
    st = app.state
    lock = lock or lock_store(s, docs)
    _book_off(app, s, lock, "no_key")
    if keyring is None:
        log.info(BOOK_OFF_NOTE)
        return
    tell = notifier or _notifier(app)
    p, mb = s.firestore_prefix, s.book_max_total_mb
    vault = DocsBookVault(docs, keyring, prefix=p, limit_mb=mb)
    st.book_source, st.book_vault = source, vault
    st.book_sealer = BookSealer(
        source,
        vault,
        docs,
        notifier=tell,
        audit=audit,
        owner_emails=s.owner_emails,
        honorific=s.user_honorific,
        limit_mb=mb,
        prefix=p,
    )
    st.book_tickets = BookTickets(docs, keyring, prefix=p, clock=book_clock(app))
    st.book_settings = BookSettingsStore(docs, prefix=p)
    wire_book_c(
        app,
        s,
        docs,
        audit,
        source=source,
        keyring=keyring,
        prefs=prefs or SettingsPrefs(st.book_settings),
        notifier=tell,
        on_close=st.book_tickets.clear,  # B-sec 4: a closed session's download tickets go too
        lock=lock,
    )
    st.book_off = None


async def wire_r6(app: FastAPI, s: Settings, docs: Docs, audit: AuditTrail) -> None:
    """Everything R6 on `app.state` (None when off), after R4 and before the gateway. A part that
    fails to build leaves the whole book off and JARVIS running (as R4's optional parts), with
    the guest lock still enforced (SEC-3)."""
    lock = lock_store(s, docs)
    try:
        wire_book(
            app,
            s,
            docs,
            audit,
            source=default_source(),
            keyring=Keyring.from_settings(s),
            lock=lock,
        )
    except Exception as exc:  # noqa: BLE001 - optional part: never fatal at start
        log.error("The build book is OFF: its setup failed", extra={"error": type(exc).__name__})
        _book_off(app, s, lock, "setup_failed")
        app.state.book_off_error = type(exc).__name__  # the class only (Vitals, L2): no message


def install_r6_routes(app: FastAPI) -> None:
    """Every Contract route, authed and no-store."""
    install_book(app)
    install_book_show(app)


def install_show_lock(app: FastAPI, s: Settings) -> None:
    """D10's guest lock over every cookie session of the owner (bearer callers untouched)."""
    install_show_lock_middleware(app, s)


def r6_tick_jobs(app: FastAPI) -> tuple[TickJob, ...]:
    """D7 `book_seal` and D14 `book_sweep` on the existing tick (no new Scheduler job), the SAME
    instances the 5-minute home watchdog runs (added to it once, when they are first built)."""
    st = app.state
    built: tuple[TickJob, ...] | None = getattr(st, "book_jobs", None)
    if built is not None:
        return built
    jobs: list[TickJob] = []
    if getattr(st, "book_sealer", None) is not None:
        jobs.append(BookSealJob(st.book_sealer, primary_user_id(st.settings)))
    if (sweep := book_sweep_job(app)) is not None:
        jobs.append(sweep)
    assert {j.name for j in jobs} <= R6_JOB_NAMES  # the names the tick checks know
    if jobs and getattr(st, "home_watchdog", None) is not None:
        for job in jobs:
            st.home_watchdog.extend(job)  # around the clock, every 5 minutes (R5.1 D4)
    out = st.book_jobs = tuple(jobs)
    return out


def r6_privacy_sources(app: FastAPI) -> tuple[PrivacySource, ...]:
    """D16: the sealed releases (passkey delete), the live session (delete = C's wipe: every
    session ends with its audit line and notice; their content-free notice records go with them)
    and Book settings (the creator name)."""
    st, s = app.state, app.state.settings
    if st.book_vault is None or st.book_service is None:
        return ()
    return (
        BookSealedSource(st.book_vault, st.book_sealer, limit_mb=s.book_max_total_mb),
        BookSessionsSource(
            st.book_sessions,
            end=_wipe(app, st.book_service),
            session_minutes=s.book_session_minutes,
            clock=book_clock(app),
        ),
        BookSettingsSource(st.book_settings),
    )


def _wipe(app: FastAPI, service: BookService) -> Callable[[str], Awaitable[int]]:
    async def end(uid: str) -> int:
        return await service.wipe(uid, now=book_now(app))

    return end


__all__ = [
    "R6_JOB_NAMES",
    "R6_STATE",
    "SETTINGS_KEYS",
    "SettingsPrefs",
    "book_clock",
    "book_now",
    "install_r6_routes",
    "install_show_lock",
    "lock_store",
    "r6_privacy_sources",
    "r6_tick_jobs",
    "wire_book",
    "wire_r6",
]
