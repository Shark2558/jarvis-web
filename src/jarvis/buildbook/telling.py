# src/jarvis/buildbook/telling.py
"""What the build book writes down and tells the owner (R6 D8, D10, D14). Content-free always:
times (the owner's time zone), minutes, counts, the audience, never a question, a reply, book text
or a token.

- `record*`: ONE audit line each (`book_open`, `book_resume`, `book_close`); False when it could
  not be written (the caller refuses whatever it was about to do).
- `notice` / `tell`: D14's `book_session_closed` ("{h}, the build book session from 14:02 has
  closed (23 min, 4 questions). Its conversation was deleted; nothing was learned from it.").
- `status` / `last_closed`: `{prefix}book_closed/{uid}` = {last_closed_at, notified} (what stays).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from jarvis.buildbook.model import ClosedSession
from jarvis.core.guardrails import ActionRisk
from jarvis.logging import get_logger
from jarvis.notify.ports import Notifier, Signal
from jarvis.storage.docs import Docs, Set

log = get_logger(__name__)

SELF_ENDED: frozenset[str] = frozenset({"expired", "idle"})
REASON_MAX = 200
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


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


def count(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def plain_reason(text: str) -> str:
    """The emergency unlock's reason as one printable line of at most REASON_MAX characters."""
    return " ".join(_CONTROL.sub(" ", text).split())[:REASON_MAX]


class Telling:
    def __init__(
        self,
        *,
        audit: Auditor | None,
        notifier: Notifier | None,
        docs: Docs,
        prefix: str = "jarvis_",
        honorific: str = "Sir",
        timezone: str = "Asia/Kolkata",
    ) -> None:
        self._audit, self._notifier, self._docs = audit, notifier, docs
        self._closed_coll = f"{prefix}book_closed"
        self.h, self._tz = honorific, ZoneInfo(timezone)

    def hhmm(self, when: str | datetime) -> str:
        moment = datetime.fromisoformat(when) if isinstance(when, str) else when
        return moment.astimezone(self._tz).strftime("%H:%M")

    # ---- words ----------------------------------------------------------------------------------
    def notice(self, closed: ClosedSession) -> str:
        """D14 (4): content-free, in the owner's time zone."""
        how = "ended by itself" if closed.reason in SELF_ENDED else "has closed"
        head = (
            f"{self.h}, the build book session from {self.hhmm(closed.created_at)} {how} "
            f"({closed.minutes} min, {count(closed.questions, 'question')})."
        )
        if closed.wiped:
            return head + " Its conversation was deleted; nothing was learned from it."
        return head + (
            " Its conversation couldn't be deleted yet; I'll keep trying. "
            "Nothing was learned from it."
        )

    def close_line(self, closed: ClosedSession) -> str:
        what = "session ended by itself" if closed.reason in SELF_ENDED else "closed"
        gone = "conversation deleted" if closed.wiped else "conversation deletion pending"
        return (
            f"Build book {what} at {self.hhmm(closed.closed_at)}, {closed.minutes} min, "
            f"{count(closed.questions, 'question')}, {gone}"
        )

    def late_line(self, closed: ClosedSession, now: datetime) -> str:
        return (
            f"Build book conversation from {self.hhmm(closed.created_at)} deleted at "
            f"{self.hhmm(now)} (its first delete had failed)"
        )

    def unlock_notice(self, now: datetime, *, lifted: bool) -> str:
        what = "the guest lock was lifted" if lifted else "nothing was locked"
        return (
            f"{self.h}, the emergency unlock ran at {self.hhmm(now)}: {what}, and no build book "
            "session was open."
        )

    # ---- writes ---------------------------------------------------------------------------------
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
        at = self.hhmm(now)
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
        at = self.hhmm(now)
        if granted:
            via = "your passkey" if how.startswith("passkey") else how
            detail, outcome = f"Guest lock lifted at {at} with {via}", "executed"
        else:
            detail, outcome = f"Guest lock kept at {at}: {how}", "refused"
        args = {"result": "granted" if granted else "refused"}
        return await self.record(uid, "book_resume", outcome, args, detail)

    async def record_close(self, uid: str, closed: ClosedSession) -> bool:
        args = {
            "minutes": closed.minutes,
            "questions": closed.questions,
            "wiped": closed.wiped,
            "audience": closed.audience,
            "reason": closed.reason,
        }
        return await self.record(uid, "book_close", "executed", args, self.close_line(closed))

    async def tell(self, uid: str, text: str) -> bool:
        if self._notifier is None:
            return False
        try:
            signal = Signal(source="system", kind="book_session_closed")
            await self._notifier.notify(uid, signal, text)
        except Exception as exc:  # noqa: BLE001 - the close stands; the status says not told
            log.error("book session notice failed", extra={"error": type(exc).__name__})
            return False
        return True

    async def status(self, uid: str, closed: ClosedSession) -> None:
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


__all__ = ["REASON_MAX", "SELF_ENDED", "Auditor", "Telling", "count", "plain_reason"]
