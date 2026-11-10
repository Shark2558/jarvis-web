# src/jarvis/buildbook/service.py
"""The build book's session lifecycle (R6 D8-D10, D13, D14): open, close, wipe, notice, sweep.

`BookService` is what the show routes (api/book_show.py) call once the HTTP checks are done
(console only, a fresh sign-in, the passkey). It never decides who may open; it records and acts:

- `open`: a guest is never shown a book naming an owner's address (D3; fail closed); audit
  `book_open` FIRST; end EVERY session of the owner (D14 "a new open"); open the new one; for a
  guest set the lock (no lock -> the guest session is closed again: never a guest without it).
- every close (End, the closing, an expired or idle session found by any request, Resume,
  Privacy -> Delete, the sweep) goes through `closing.ClosingStore.close_claim` (D14 1-2: closing,
  delete, read back) and says whether THIS caller tells; the caller that does runs `on_close` (I1:
  B's download tickets go), writes ONE content-free `book_close` line (3), sends ONE
  `book_session_closed` notice (4), keeps `{last_closed_at, notified}` and marks the notice told.
- `sweep` closes and tells session by session; `emergency_unlock` (buildbook/unlock.py, the
  server's own credentials) recovers a passkey lost during a guest show.
- `script` / `line_text` / `ask`: facts only from book.json, D13's fixed lines, a reply spoken by
  its id. A guest never gets the owner's spend. Nothing here logs a question, reply or token.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from jarvis.buildbook import guard
from jarvis.buildbook.closing import Closing, Sweeping
from jarvis.buildbook.lines import LINES
from jarvis.buildbook.model import (
    Audience,
    ClosedSession,
    CloseReason,
    OpenedSession,
    SessionView,
    ShowLockState,
    TalkReply,
    TalkState,
)
from jarvis.buildbook.ports import (
    BookOff,
    BookSource,
    BookTalker,
    BookUnavailable,
    SessionGone,
    ShowLock,
)
from jarvis.buildbook.sessions import GONE, SessionEnded
from jarvis.buildbook.show_script import Prefs, ShowScript
from jarvis.buildbook.telling import SELF_ENDED, Auditor, Telling, plain_reason
from jarvis.logging import get_logger
from jarvis.notify.ports import Notifier
from jarvis.storage.docs import Docs

log = get_logger(__name__)

SPEAK_CHARS_PER_SESSION = 24_000  # ~4x the show's ~6,000 narrated characters (D15)
HEARS_PER_SESSION = 30  # spoken questions: 20 questions and some retries (15 s each)
_KEEP_COUNTERS = 256
NOT_RECORDED = "The build book couldn't record this, so nothing was opened."
NO_LOCK = "The guest lock couldn't be set, so the guest session was not opened."
NO_BOOK = "This server has no build book."
NAMES_OWNER = "This release's build book names your e-mail address, so a guest can't see it."
UNLOCK_NOT_RECORDED = "The emergency unlock couldn't be recorded, so nothing was changed."
REPLY_ID = re.compile(r"r_[0-9a-f]{12}")  # a guarded reply the show speaks by its id (I1)


@dataclass(frozen=True)
class SweepReport:
    closed: tuple[ClosedSession, ...]
    errors: int  # sessions that couldn't be closed this time (the next sweep retries)


@dataclass(frozen=True)
class UnlockReport:
    lifted: bool  # a guest lock was on and is gone
    closed: int  # book sessions ended (each told with its own notice)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class BookService:
    def __init__(
        self,
        *,
        source: BookSource,
        sessions: Sweeping,
        lock: ShowLock | None,
        talk: BookTalker | None,
        audit: Auditor | None,
        notifier: Notifier | None,
        docs: Docs,
        prefix: str = "jarvis_",
        honorific: str = "Sir",
        timezone: str = "Asia/Kolkata",
        prefs: Prefs | None = None,
        spend: Callable[[str], Awaitable[Mapping[str, Any]]] | None = None,
        owner_emails: Sequence[str] = (),
        on_close: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self.source, self.sessions, self.lock, self.talk = source, sessions, lock, talk
        self._on_close = on_close
        self.tell = Telling(audit=audit, notifier=notifier, docs=docs, prefix=prefix,
                            honorific=honorific, timezone=timezone)  # fmt: skip
        self.show = ShowScript(source, honorific=honorific, prefs=prefs, spend=spend)
        self._owners = tuple(owner_emails)
        self._guest_ok: tuple[str, str | None] | None = None  # (release id, refusal)
        self._spoken: dict[str, int] = {}  # per instance: a guest can't spend the voice budget
        self._heard: dict[str, int] = {}

    # ---- words, audit, status (buildbook/telling.py) --------------------------------------------
    async def record_open(
        self, uid: str, audience: str, *, granted: bool, how: str, now: datetime
    ) -> bool:
        return await self.tell.record_open(uid, audience, granted=granted, how=how, now=now)

    async def record_resume(self, uid: str, *, granted: bool, how: str, now: datetime) -> bool:
        return await self.tell.record_resume(uid, granted=granted, how=how, now=now)

    async def last_closed(
        self, uid: str
    ) -> dict[str, Any] | None:  # B's {last_closed_at, notified}
        return await self.tell.last_closed(uid)

    # ---- D3 at a guest's door -------------------------------------------------------------------
    def guest_refusal(self) -> str | None:
        """None when a guest may be shown this release's book; else plain words why not. A book
        naming an owner (D3 amendment: `owner_id`) is refused, as the sealer refuses it; a
        book that can't be read is refused too (and checked again next time)."""
        rel = self.source.current()
        if rel is None or not rel.ok:
            return NO_BOOK
        if self._guest_ok is not None and self._guest_ok[0] == rel.id:
            return self._guest_ok[1]
        try:
            data = self.source.read("book")
        except Exception as exc:  # noqa: BLE001 - can't tell: no guest
            log.warning("build book unreadable for a guest", extra={"error": type(exc).__name__})
            return NO_BOOK
        why = NAMES_OWNER if guard.book_names_owner(data, self._owners) else None
        if why is not None:
            log.error("the build book names an owner: no guest may open it")
        self._guest_ok = (rel.id, why)
        return why

    def guest_book_ok(self) -> bool:
        return self.guest_refusal() is None

    def _guest_check(self, audience: Audience) -> None:
        if audience == "guest" and (why := self.guest_refusal()) is not None:
            raise BookUnavailable(why)

    # ---- the voice budget (a guest must not run up the owner's speech bill) -------------------
    @staticmethod
    def _spend_counter(counter: dict[str, int], session_id: str, amount: int, cap: int) -> bool:
        used = counter.get(session_id, 0) + amount
        if used > cap:
            return False
        counter[session_id] = used
        while len(counter) > _KEEP_COUNTERS:
            counter.pop(next(iter(counter)))
        return True

    def allow_speech(self, session_id: str, chars: int) -> bool:
        """Cloud voice for `chars` more characters in this session? (Else the browser voice.)"""
        return self._spend_counter(self._spoken, session_id, chars, SPEAK_CHARS_PER_SESSION)

    def allow_hearing(self, session_id: str) -> bool:
        return self._spend_counter(self._heard, session_id, 1, HEARS_PER_SESSION)

    # ---- closing and telling (exactly once: closing.py) -----------------------------------------
    async def _finish(self, closing: Closing, now: datetime) -> ClosedSession:
        """D14 steps 3-4 after the store's 1-2, for the caller holding the claim only."""
        closed, uid = closing.closed, closing.uid
        self._spoken.pop(closed.session_id, None)
        self._heard.pop(closed.session_id, None)
        if closing.late_wipe:  # told before ("couldn't be deleted yet"): one audit line, no notice
            args = {"wiped": True, "late": True, "audience": closed.audience}
            await self.tell.record(
                uid, "book_close", "executed", args, self.tell.late_line(closed, now)
            )
            await self.sessions.told(uid, closed.session_id, wiped=True)
            return closed
        if not closing.claimed:
            return closed
        await self._closed(uid)
        await self.tell.record_close(uid, closed)
        sent = await self.tell.tell(uid, self.tell.notice(closed))
        done = closed.model_copy(update={"notified": sent})
        await self.tell.status(uid, done)
        await self.sessions.told(uid, closed.session_id, wiped=closed.wiped)
        return done

    async def _closed(self, uid: str) -> None:
        """What else ends with a session (I1: B's download tickets), best effort."""
        if self._on_close is None:
            return
        try:
            await self._on_close(uid)
        except Exception as exc:  # noqa: BLE001 - a download checks its session anyway
            log.warning("book close hook failed", extra={"error": type(exc).__name__})

    async def _end_all(self, uid: str, reason: CloseReason, now: datetime) -> list[ClosedSession]:
        """Close EVERY session of the owner (open, expired, idle or still closing), each told."""
        done: list[ClosedSession] = []
        for bk in await self.sessions.owned_ids(uid):
            closing = await self.sessions.close_claim(uid, bk, reason, now, by_due=True)
            if closing is not None:
                done.append(await self._finish(closing, now))
        return done

    # ---- the lifecycle ---------------------------------------------------------------------------
    async def open(self, uid: str, audience: Audience, *, how: str, now: datetime) -> OpenedSession:
        self._guest_check(audience)
        if not await self.record_open(uid, audience, granted=True, how=how, now=now):
            raise BookOff(NOT_RECORDED)
        await self._end_all(uid, "new_open", now)
        opened, _racing = await self.sessions.open(uid, audience, now=now)  # its claim: the sweep
        if audience == "guest":
            await self._lock_guest(uid, opened, now)
        return opened

    async def _lock_guest(self, uid: str, opened: OpenedSession, now: datetime) -> None:
        sid = opened.session.session_id
        try:
            if self.lock is None:
                raise RuntimeError("no lock store")
            await self.lock.set(uid, sid, now=now)
        except Exception as exc:  # noqa: BLE001 - fail closed: no guest without the lock
            log.error("guest lock not set", extra={"error": type(exc).__name__})
            await self.close(uid, sid, reason="end", now=now)
            raise BookOff(NO_LOCK) from None

    async def resolve(self, uid: str, token: str, *, now: datetime) -> SessionView:
        try:
            return await self.sessions.resolve(uid, token, now=now)
        except SessionEnded as gone:
            await self._finish(gone.closing, now)
            raise

    async def beat(self, uid: str, token: str, *, now: datetime) -> SessionView:
        try:
            return await self.sessions.beat(uid, token, now=now)
        except SessionEnded as gone:
            await self._finish(gone.closing, now)
            raise

    async def close(
        self, uid: str, session_id: str, *, reason: CloseReason, now: datetime
    ) -> ClosedSession:
        closing = await self.sessions.close_claim(uid, session_id, reason, now)
        if closing is None:
            raise SessionGone(GONE)
        return await self._finish(closing, now)

    async def lock_state(self, uid: str) -> ShowLockState | None:
        return None if self.lock is None else await self.lock.get(uid)

    async def resume(
        self, uid: str, lock_id: str, *, now: datetime, signed_out_before: float | None = None
    ) -> bool:
        """Lift the guest lock (book_resume proof checked) and end every session of the owner
        (D14 "Resume"); cookies issued before `signed_out_before` stop counting (SEC-4)."""
        if not await self._lift(uid, lock_id, signed_out_before):
            return False
        try:
            await self._end_all(uid, "resume", now)
        except Exception as exc:  # noqa: BLE001 - the lock is lifted; the sweep ends the rest
            log.error("book sessions not ended at resume", extra={"error": type(exc).__name__})
        return True

    async def wipe(self, uid: str, *, now: datetime) -> int:
        """Privacy -> Delete (D16): end and wipe EVERY session; how many."""
        return len(await self._end_all(uid, "privacy", now))

    async def _swept(self, step: Awaitable[Closing | None], now: datetime) -> ClosedSession | None:
        closing = await step
        return None if closing is None else await self._finish(closing, now)

    async def sweep(self, *, now: datetime) -> SweepReport:
        """Close what is over, one session at a time (each told at once), and recover closes
        whose closer died before telling. A failure is counted and retried next time."""
        done: list[ClosedSession] = []
        errors = 0
        steps = [
            self.sessions.close_claim(uid, bk, "expired", now, due_only=True)
            for uid, bk in await self.sessions.sweep_targets(now=now)
        ]
        steps += [
            self.sessions.claim_orphan(uid, bk, now)
            for uid, bk in await self.sessions.orphans(now=now)
        ]
        for step in steps:
            try:
                closed = await self._swept(step, now)
            except Exception as exc:  # noqa: BLE001 - the others still close and tell
                errors += 1
                log.warning("a book session didn't close", extra={"error": type(exc).__name__})
                continue
            done += [closed] if closed is not None else []
        return SweepReport(tuple(done), errors)

    async def emergency_unlock(
        self, uid: str, reason: str, *, now: datetime, signed_out_before: float | None = None
    ) -> UnlockReport:
        """A passkey lost during a guest show (buildbook/unlock.py): audit FIRST, lift the lock,
        end every session (each told); a notice even when none was open."""
        state = await self.fresh_lock_state(uid)
        detail = (
            f"Emergency unlock at {self.tell.hhmm(now)} from Google Cloud (no passkey): "
            f"{plain_reason(reason)}"
        )
        args = {"result": "granted", "via": "emergency_unlock", "locked": state is not None}
        if not await self.tell.record(uid, "book_resume", "executed", args, detail):
            raise BookOff(UNLOCK_NOT_RECORDED)
        lifted = state is not None and await self._lift(uid, state.id, signed_out_before)
        closed = await self._end_all(uid, "resume", now)
        if not closed:
            await self.tell.tell(uid, self.tell.unlock_notice(now, lifted=lifted))
        return UnlockReport(lifted=lifted, closed=len(closed))

    async def fresh_lock_state(self, uid: str) -> ShowLockState | None:
        """The lock read past any cache (the emergency unlock acts on what is there now)."""
        if self.lock is None:
            return None
        refresh = getattr(self.lock, "refresh", None)
        state = await refresh(uid) if callable(refresh) else await self.lock.get(uid)
        return state if isinstance(state, ShowLockState) else None

    async def _lift(self, uid: str, lock_id: str, after: float | None = None) -> bool:
        return self.lock is not None and await self.lock.lift(uid, lock_id, signed_out_before=after)

    # ---- the show and the talk-through -----------------------------------------------------------
    async def line_text(self, uid: str, session: SessionView, line_id: str) -> str | None:
        """What `POST /v1/book/show/speak {line_id}` reads: a beat, a D13 line or a reply."""
        self._guest_check(session.audience)
        if REPLY_ID.fullmatch(line_id):
            said = getattr(self.talk, "said", None)
            return None if said is None else await said(uid, session.session_id, line_id)
        return await self.show.line_text(uid, line_id)

    async def voice(self, uid: str) -> str:
        return await self.show.voice(uid)

    async def talk_state(self, uid: str) -> TalkState:
        if self.talk is None:
            return TalkState(on=False, why="Questions aren't available on this server.")
        return await self.talk.state(uid)

    async def ask(self, uid: str, session: SessionView, text: str, *, now: datetime) -> TalkReply:
        self._guest_check(session.audience)
        if self.talk is not None:
            return await self.talk.ask(uid, session, text, now=now)
        left = session.questions_left
        follow = LINES["anything_else"] if left else LINES["limit"]
        return TalkReply(
            reply_id="r_000000000000",
            reply=LINES["ai_off"],
            refused=True,
            follow_up=follow,
            left=left,
        )

    async def script(self, uid: str, session: SessionView) -> dict[str, Any]:
        """`GET /v1/book/show/script` (buildbook/show_script.py)."""
        self._guest_check(session.audience)
        return await self.show.build(uid, session, await self.talk_state(uid))


class BookSweepJob:
    """D14's `book_sweep` TickJob: abandoned sessions end by themselves; failed deletes retry;
    closes whose closer died before telling are told."""

    name = "book_sweep"
    budget_s = 30.0

    def __init__(self, service: BookService, *, clock: Callable[[], datetime] = _utcnow) -> None:
        self._svc, self._clock = service, clock

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        report = await self._svc.sweep(now=self._clock())
        wiped = sum(1 for c in report.closed if c.wiped)
        return {"closed": wiped, "failed": len(report.closed) - wiped + report.errors}


__all__ = [
    "SELF_ENDED",
    "BookService",
    "BookSweepJob",
    "SweepReport",
    "UnlockReport",
]
