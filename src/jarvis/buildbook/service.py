# src/jarvis/buildbook/service.py
"""The build book's session lifecycle (R6 D8-D10, D13, D14): open, close, wipe, notice, sweep.

`BookService` is what the show routes (api/book_show.py) call once the HTTP checks are done
(console only, a fresh sign-in, the passkey). It never decides who may open; it records and acts:

- `open`: audit `book_open` FIRST (nothing opens when it can't be written), end the live session
  (D14 trigger "a new open"), open the new one, and for a guest set the lock (no lock -> the guest
  session is closed again and the open fails: never a guest session without its lock).
- `close` (and `resolve`/`beat` finding an expired or idle session, `resume`, `wipe`, the sweep):
  the store marks closing, deletes and reads back (D14 1-2); then ONE content-free `book_close`
  audit line (3), ONE `book_session_closed` notice (4) and `{last_closed_at, notified}` in
  `{prefix}book_closed/{uid}` (what stays). A delete retried by the sweep is not told twice.
- `script` / `line_text`: the show's facts come only from book.json; scenes 12 and 13 and every
  refusal are D13's fixed lines. A guest never gets the owner's month spend (D1).
- `BookSweepJob`: the `book_sweep` TickJob (I1 adds it to the tick and R5.1's watchdog list).
Nothing here logs or stores a question, a reply or a token.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from jarvis.buildbook.lines import LINES
from jarvis.buildbook.model import (
    LINE_ID,
    Audience,
    ClosedSession,
    CloseReason,
    OpenedSession,
    SessionView,
    ShowLockState,
    TalkReply,
    TalkState,
)
from jarvis.buildbook.ports import BookOff, BookSessions, BookSource, BookTalker, ShowLock
from jarvis.buildbook.sessions import SessionEnded
from jarvis.buildbook.show_script import Prefs, ShowScript
from jarvis.core.guardrails import ActionRisk
from jarvis.logging import get_logger
from jarvis.notify.ports import Notifier, Signal
from jarvis.storage.docs import Docs, Set

log = get_logger(__name__)

SELF_ENDED: frozenset[str] = frozenset({"expired", "idle"})
SPEAK_CHARS_PER_SESSION = 24_000  # ~4x the show's ~6,000 narrated characters (D15)
HEARS_PER_SESSION = 30  # spoken questions: 20 questions and some retries (15 s each)
_KEEP_COUNTERS = 256
NOT_RECORDED = "The build book couldn't record this, so nothing was opened."
NO_LOCK = "The guest lock couldn't be set, so the guest session was not opened."
_LINE = re.compile(LINE_ID)


class Auditor(Protocol):
    async def append(
        self,
        *,
        agent: str,
        tool: str,
        risk: ActionRisk,
        outcome: str,
        args: dict[str, Any],
        detail: str = "",
    ) -> Any: ...


class Sweeping(BookSessions, Protocol):
    async def sweep_owned(self, *, now: datetime) -> tuple[tuple[str, ClosedSession], ...]: ...


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _count(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


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
    ) -> None:
        self.source, self.sessions, self.lock, self.talk = source, sessions, lock, talk
        self._audit, self._notifier, self._docs = audit, notifier, docs
        self._closed_coll = f"{prefix}book_closed"
        self._h, self._tz = honorific, ZoneInfo(timezone)
        self.show = ShowScript(source, honorific=honorific, prefs=prefs, spend=spend)
        self._spoken: dict[str, int] = {}  # per instance: a guest can't spend the voice budget
        self._heard: dict[str, int] = {}

    # ---- words -----------------------------------------------------------------------------------
    def _hhmm(self, at: str | datetime) -> str:
        when = datetime.fromisoformat(at) if isinstance(at, str) else at
        return when.astimezone(self._tz).strftime("%H:%M")

    def notice(self, closed: ClosedSession) -> str:
        """D14 (4): content-free, in the owner's time zone."""
        how = "ended by itself" if closed.reason in SELF_ENDED else "has closed"
        head = (
            f"{self._h}, the build book session from {self._hhmm(closed.created_at)} {how} "
            f"({closed.minutes} min, {_count(closed.questions, 'question')})."
        )
        if closed.wiped:
            return head + " Its conversation was deleted; nothing was learned from it."
        return head + (
            " Its conversation couldn't be deleted yet; I'll keep trying. "
            "Nothing was learned from it."
        )

    def _close_line(self, closed: ClosedSession) -> str:
        what = "session ended by itself" if closed.reason in SELF_ENDED else "closed"
        gone = "conversation deleted" if closed.wiped else "conversation deletion pending"
        return (
            f"Build book {what} at {self._hhmm(closed.closed_at)}, {closed.minutes} min, "
            f"{_count(closed.questions, 'question')}, {gone}"
        )

    # ---- audit, notice, status -------------------------------------------------------------------
    async def record(
        self, uid: str, tool: str, outcome: str, args: dict[str, Any], detail: str
    ) -> bool:
        """One content-free audit line; False when it could not be written (the caller acts)."""
        if self._audit is None:
            log.error("no audit chain: a build book event is refused", extra={"tool": tool})
            return False
        try:
            await self._audit.append(
                agent="owner",
                tool=tool,
                risk=ActionRisk.READ_ONLY,
                outcome=outcome,
                args={"user": uid, **args},
                detail=detail,
            )
        except Exception as exc:  # noqa: BLE001 - reported to the caller as False
            log.error(
                "AUDIT WRITE FAILED for the build book",
                extra={"tool": tool, "error": type(exc).__name__},
            )
            return False
        return True

    async def record_open(
        self, uid: str, audience: str, *, granted: bool, how: str, now: datetime
    ) -> bool:
        at = self._hhmm(now)
        whom = "for a guest" if audience == "guest" else "for you"
        if granted:
            via = "with your passkey" if how.startswith("passkey") else f"({how})"
            detail = f"Build book opened {via} at {at}, {whom}"
        else:
            detail = f"Build book open refused at {at}, {whom}: {how}"
        result = "granted" if granted else "refused"
        args = {"audience": audience, "result": result}
        return await self.record(
            uid, "book_open", "executed" if granted else "refused", args, detail
        )

    async def record_resume(self, uid: str, *, granted: bool, how: str, now: datetime) -> bool:
        at = self._hhmm(now)
        if granted:
            via = "your passkey" if how.startswith("passkey") else how
            detail, outcome = f"Guest lock lifted at {at} with {via}", "executed"
        else:
            detail, outcome = f"Guest lock kept at {at}: {how}", "refused"
        args = {"result": "granted" if granted else "refused"}
        return await self.record(uid, "book_resume", outcome, args, detail)

    async def _tell(self, uid: str, closed: ClosedSession) -> bool:
        if self._notifier is None:
            return False
        try:
            signal = Signal(source="system", kind="book_session_closed")
            await self._notifier.notify(uid, signal, self.notice(closed))
        except Exception as exc:  # noqa: BLE001 - the close stands; the status says not told
            log.error("book session notice failed", extra={"error": type(exc).__name__})
            return False
        return True

    async def _status(self, uid: str, closed: ClosedSession) -> None:
        doc = {"last_closed_at": closed.closed_at, "notified": closed.notified}
        try:
            await self._docs.write([Set(f"{self._closed_coll}/{uid}", doc)])
        except Exception as exc:  # noqa: BLE001 - a status line, never worth failing a close
            log.warning("book close status not written", extra={"error": type(exc).__name__})

    async def last_closed(self, uid: str) -> dict[str, Any] | None:
        """For B's `GET /v1/book` (`last_closed`): {last_closed_at, notified} or None."""
        raw = await self._docs.get(f"{self._closed_coll}/{uid}")
        if raw is None:
            return None
        return {"last_closed_at": raw.get("last_closed_at"), "notified": bool(raw.get("notified"))}

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

    async def _finish(self, uid: str, closed: ClosedSession) -> ClosedSession:
        """D14 steps 3-4 after the store's 1-2. A retried delete (`notified` already) only
        updates nothing: the owner was told the first time."""
        self._spoken.pop(closed.session_id, None)
        self._heard.pop(closed.session_id, None)
        if closed.notified:
            return closed
        args = {
            "minutes": closed.minutes,
            "questions": closed.questions,
            "wiped": closed.wiped,
            "audience": closed.audience,
            "reason": closed.reason,
        }
        await self.record(uid, "book_close", "executed", args, self._close_line(closed))
        done = closed.model_copy(update={"notified": await self._tell(uid, closed)})
        await self._status(uid, done)
        return done

    # ---- the lifecycle ---------------------------------------------------------------------------
    async def open(self, uid: str, audience: Audience, *, how: str, now: datetime) -> OpenedSession:
        if not await self.record_open(uid, audience, granted=True, how=how, now=now):
            raise BookOff(NOT_RECORDED)
        live = await self.sessions.live(uid, now=now)
        if live is not None:
            await self.close(uid, live.session_id, reason="new_open", now=now)
        opened, ended = await self.sessions.open(uid, audience, now=now)
        if ended is not None:
            await self._finish(uid, ended)
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

    async def _ended(self, uid: str, gone: SessionEnded) -> None:
        await self._finish(uid, gone.closed)

    async def resolve(self, uid: str, token: str, *, now: datetime) -> SessionView:
        try:
            return await self.sessions.resolve(uid, token, now=now)
        except SessionEnded as gone:
            await self._ended(uid, gone)
            raise

    async def beat(self, uid: str, token: str, *, now: datetime) -> SessionView:
        try:
            return await self.sessions.beat(uid, token, now=now)
        except SessionEnded as gone:
            await self._ended(uid, gone)
            raise

    async def close(
        self, uid: str, session_id: str, *, reason: CloseReason, now: datetime
    ) -> ClosedSession:
        closed = await self.sessions.close(uid, session_id, reason=reason, now=now)
        return await self._finish(uid, closed)

    async def lock_state(self, uid: str) -> ShowLockState | None:
        return None if self.lock is None else await self.lock.get(uid)

    async def resume(self, uid: str, lock_id: str, *, now: datetime) -> bool:
        """Lift the guest lock (the caller checked the book_resume proof for `lock_id`) and end
        whatever session is still live (D14 trigger "Resume")."""
        if self.lock is None or not await self.lock.lift(uid, lock_id):
            return False
        live = await self.sessions.live(uid, now=now)
        if live is not None:
            await self.close(uid, live.session_id, reason="resume", now=now)
        return True

    async def wipe(self, uid: str, *, now: datetime) -> int:
        """Privacy -> Delete (D16 `book_sessions_source`): end and wipe the live session."""
        live = await self.sessions.live(uid, now=now)
        if live is None:
            return 0
        await self.close(uid, live.session_id, reason="privacy", now=now)
        return 1

    async def sweep(self, *, now: datetime) -> tuple[ClosedSession, ...]:
        done = [await self._finish(uid, c) for uid, c in await self.sessions.sweep_owned(now=now)]
        return tuple(done)

    # ---- the show and the talk-through -----------------------------------------------------------
    async def line_text(self, uid: str, session: SessionView, line_id: str) -> str | None:
        """What `POST /v1/book/show/speak {line_id}` reads: a beat of this book or a D13 line."""
        return await self.show.line_text(uid, line_id)

    async def voice(self, uid: str) -> str:
        return await self.show.voice(uid)

    async def talk_state(self, uid: str) -> TalkState:
        if self.talk is None:
            return TalkState(on=False, why="Questions aren't available on this server.")
        return await self.talk.state(uid)

    async def ask(self, uid: str, session: SessionView, text: str, *, now: datetime) -> TalkReply:
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
        return await self.show.build(uid, session, await self.talk_state(uid))


class BookSweepJob:
    """D14's `book_sweep` TickJob: abandoned sessions end by themselves; failed deletes retry."""

    name = "book_sweep"
    budget_s = 30.0

    def __init__(self, service: BookService, *, clock: Callable[[], datetime] = _utcnow) -> None:
        self._svc, self._clock = service, clock

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        closed = await self._svc.sweep(now=self._clock())
        wiped = sum(1 for c in closed if c.wiped)
        return {"closed": wiped, "failed": len(closed) - wiped}


__all__ = ["SELF_ENDED", "BookService", "BookSweepJob"]
