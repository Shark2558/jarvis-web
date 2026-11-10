# src/jarvis/buildbook/unlock.py
"""The emergency unlock: the owner lost his passkey during a guest show (R6 D10 "Risks").

    python -m jarvis.buildbook.unlock --owner you@gmail.com --reason "lost my passkey" [--yes]

D10 lifts a guest lock with a `book_resume` passkey only; no browser sign-in ever does (a guest
can make a "fresh" one with a click). This command is the one other way, and it never goes
through the browser: it runs with the server's OWN Google Cloud credentials (Firestore, and the
Telegram token from Secret Manager), so only someone holding the owner's Google Cloud access can
run it. It needs NO token key (integrated review SEC-6): lifting the lock and closing sessions
touch no key. It shows what is locked, asks before changing anything (`--yes` skips the
question), then: audit line FIRST (no audit, no change) -> lift the lock, ending every owner's
cookie sessions issued before the moment of the lift, even one made while it asked (SEC-4) ->
end every build book session of the owner (each told with `book_session_closed`) -> a notice
even when none was open. A lock on ANOTHER owner holds these consoles too: it is named, nothing
changes, and the exit code is 1. Exit codes: 0 done (or nothing to do), 1 not done (declined,
unreadable, not recorded, another owner's lock), 2 refused (not an owner, no reason, not the
server's Firestore). The runbook is in INTEGRATION-C.md.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime

from jarvis.buildbook.model import Book, FileKind, Release
from jarvis.buildbook.ports import BookOff, BookUnavailable, LockUnreadable
from jarvis.buildbook.service import BookService, UnlockReport
from jarvis.buildbook.telling import count, plain_reason
from jarvis.config import SessionBackend, Settings, get_settings

KEPT = "Nothing changed: the lock and the sessions are as they were."
NOTHING = "Nothing is locked and no build book session is open; nothing to do."
NEEDS_FIRESTORE = (
    "This needs the server's Firestore: set JARVIS_SESSION_BACKEND=firestore and "
    "JARVIS_FIRESTORE_PROJECT (see the runbook)."
)
OTHER_LOCK = (
    "A lock on another owner holds these consoles. Nothing changed: run this again with "
    "--owner set to that owner."
)
NOT_OWNER = "That isn't one of this JARVIS's owners (JARVIS_OWNER_EMAILS)."
NO_REASON = "Say why in --reason (a few words; it goes into the audit)."
ABOUT = "Lift a guest lock without the passkey: the owner only, with the server's own credentials."
ASK = "Lift the guest lock and end every build book session? Type yes to go on: "

Ask = Callable[[str], bool | Awaitable[bool]]  # input() in a shell; a test may await


class UnlockUnavailable(RuntimeError):
    """This shell can't reach the server's own storage or key: nothing was done."""


class _NoBook:
    """The unlock never reads the book (ports.BookSource)."""

    def current(self) -> Release | None:
        return None

    def read(self, kind: FileKind) -> bytes:
        raise BookUnavailable("The emergency unlock reads no book.")

    def book(self) -> Book:
        raise BookUnavailable("The emergency unlock reads no book.")


def build_service(s: Settings) -> BookService:
    """The book service on the server's own Firestore, audit chain and Telegram."""
    from jarvis.alerts import AlertSink, NoAlerts
    from jarvis.api.telegram import build_telegram
    from jarvis.buildbook.lock import DocShowLock
    from jarvis.buildbook.sessions import DocBookSessions
    from jarvis.notify.ports import DirectNotifier
    from jarvis.storage import build_storage

    if s.session_backend is not SessionBackend.FIRESTORE or not s.firestore_project:
        raise UnlockUnavailable(NEEDS_FIRESTORE)
    built = build_storage(s)
    if built.docs is None:
        raise UnlockUnavailable(NEEDS_FIRESTORE)
    p, docs = s.firestore_prefix, built.docs
    telegram = build_telegram(s, docs, audit=built.audit)
    sink: AlertSink = telegram.alerts if telegram is not None else NoAlerts("no Telegram")
    sessions = DocBookSessions(
        docs,
        None,  # SEC-6: closing needs no key; the lock and the closer are built without one
        prefix=p,
        session_minutes=s.book_session_minutes,
        idle_minutes=s.book_idle_minutes,
        questions=s.book_talk_questions,
    )
    return BookService(
        source=_NoBook(),
        sessions=sessions,
        lock=DocShowLock(docs, prefix=p, cache_s=0, owners=owner_uids(s)),
        talk=None,
        audit=built.audit,
        notifier=DirectNotifier(sink),
        docs=docs,
        prefix=p,
        honorific=s.user_honorific,
        timezone=s.user_timezone,
    )


def owner_uids(s: Settings) -> tuple[str, ...]:
    from jarvis.api.identity import user_id_for_email

    return tuple(dict.fromkeys(user_id_for_email(e) for e in s.owner_emails))


def owner_uid(s: Settings, owner: str) -> str | None:
    """The owner's id from his e-mail or his id, only when he is one of this JARVIS's owners."""
    from jarvis.api.identity import user_id_for_email

    ids = {e.strip().lower(): user_id_for_email(e) for e in s.owner_emails}
    wanted = owner.strip().lower()
    if wanted in ids:
        return ids[wanted]
    return wanted if wanted in ids.values() else None


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="python -m jarvis.buildbook.unlock", description=ABOUT)
    ap.add_argument("--owner", required=True, help="the owner's e-mail (or his u_... id)")
    ap.add_argument("--reason", required=True, help="why, in a few words (audited)")
    ap.add_argument("--yes", action="store_true", help="don't ask before unlocking")
    return ap.parse_args(argv)


def _done(report: UnlockReport) -> str:
    lock = "The guest lock was lifted" if report.lifted else "No guest lock was on"
    return f"{lock}; {count(report.closed, 'build book session')} ended. The owner was told."


async def _other_lock(svc: BookService, others: Sequence[str]) -> bool:
    return any([await svc.fresh_lock_state(o) is not None for o in others])


async def _yes(ask: Ask) -> bool:
    answer = ask(ASK)
    return bool(await answer) if inspect.isawaitable(answer) else bool(answer)


async def _unlock(
    svc: BookService,
    uid: str,
    reason: str,
    *,
    ask: Ask,
    out: Callable[[str], None],
    clock: Callable[[], datetime],
    others: Sequence[str] = (),
) -> int:
    try:
        state = await svc.fresh_lock_state(uid)
        if state is None and await _other_lock(svc, others):
            out(OTHER_LOCK)  # A's lock holds B's consoles too (book_lock.lock_for): not B's to lift
            return 1
    except LockUnreadable:
        out("The guest lock can't be read right now. " + KEPT)
        return 1
    sessions = len(await svc.sessions.owned_ids(uid))
    if state is None and not sessions:
        out(NOTHING)
        return 0
    since = f"on since {svc.tell.hhmm(state.since)}" if state is not None else "off"
    out(f"Guest lock: {since}. Build book sessions: {sessions}.")
    if not await _yes(ask):
        out(KEPT)
        return 1
    now = clock()  # at the lift, not at the start: a sign-in made while asked stops counting too
    try:  # SEC-4: every owner's cookie session issued before now stops counting
        report = await svc.emergency_unlock(uid, reason, now=now, signed_out_before=now.timestamp())
    except BookOff as exc:
        out(str(exc))
        return 1
    out(_done(report))
    return 0 if report.lifted or state is None else 1


def _ask(prompt: str) -> bool:
    return input(prompt).strip().lower() == "yes"


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def amain(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    build: Callable[[Settings], BookService] = build_service,
    confirm: Ask = _ask,
    out: Callable[[str], None] = print,
    clock: Callable[[], datetime] = _utcnow,
) -> int:
    args = _parse(argv)
    s = settings or get_settings()
    uid, reason = owner_uid(s, args.owner), plain_reason(args.reason)
    if uid is None or len(reason) < 3:
        out(NOT_OWNER if uid is None else NO_REASON)
        return 2
    try:
        svc = build(s)
    except UnlockUnavailable as exc:
        out(str(exc))
        return 2
    ask = (lambda _prompt: True) if args.yes else confirm
    others = [o for o in owner_uids(s) if o != uid]
    return await _unlock(svc, uid, reason, ask=ask, out=out, clock=clock, others=others)


def main(argv: Sequence[str] | None = None, **kw: object) -> int:
    return asyncio.run(amain(argv, **kw))  # type: ignore[arg-type]


__all__ = [
    "OTHER_LOCK",
    "UnlockReport",
    "UnlockUnavailable",
    "amain",
    "build_service",
    "main",
    "owner_uid",
    "owner_uids",
]


if __name__ == "__main__":
    raise SystemExit(main())
