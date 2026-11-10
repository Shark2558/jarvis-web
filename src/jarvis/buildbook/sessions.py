# src/jarvis/buildbook/sessions.py
"""Build book sessions on the document store (R6 D9, D14; `ports.BookSessions`).

`{prefix}book_sessions/{bk}` = {v, uid, audience, mac, created_at, last_seen, until, idle_until,
questions, state (open | closing), reason, blob}. The token is 32 random bytes (base64url) shown
ONCE; only `Keyring.mac("book_session", token)` is stored, and a request finds its session by that
MAC (an equality query: no scan, no token at rest). `blob` = the last 8 guarded turns sealed under
keyring purpose `book_session` with AAD `book/session/{uid}/{bk}/v1`, so a blob copied to another
owner's or session's document does not open. One live session per owner: `open` ends every other
one first (reason new_open). 45 minutes absolute, 10 idle (Settings `book_session_minutes`,
`book_idle_minutes`); the show's beat moves the idle limit, never the absolute one.

Close (D14): `closing.ClosingStore` (mixed in): mark `closing` and drop the turns in the same
transaction that claims the notice, delete, read back. The talk lane RESERVES a question in a
transaction before its model call (`reserve`; refused at the session's limit, so parallel asks
can't run past it), gives it back when no call was made (`release`) and stores the guarded turn
without counting it again (`put_turn`). Nothing here logs a token, a question or a reply.
"""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timedelta
from typing import Any

from pydantic import ValidationError

from jarvis.buildbook.closing import Closing, ClosingStore, at, due
from jarvis.buildbook.model import (
    Audience,
    ClosedSession,
    CloseReason,
    OpenedSession,
    SessionView,
)
from jarvis.buildbook.ports import SessionGone
from jarvis.integrations.vault import VaultError
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.storage.docs import Create, Docs, DocTx, Query

log = get_logger(__name__)

PURPOSE = "book_session"
TURNS_KEPT = 8  # D11: the talk lane's context is this session's last 8 turns
TOKEN_BYTES = 32
_TOKEN = re.compile(r"^[A-Za-z0-9_\-]{43,128}$")
GONE = "This build book session has ended. Open the book again from the console."


class SessionEnded(SessionGone):
    """The session was expired or idle and has just been closed. `closing.claimed`: the caller
    tells the owner (BookService does; a caller that doesn't leaves it to the sweep)."""

    def __init__(self, closing: Closing) -> None:
        self.closing = closing
        super().__init__(GONE)

    @property
    def closed(self) -> ClosedSession:
        return self.closing.closed


def _check_limits(session_minutes: int, idle_minutes: int, questions: int) -> None:
    if not 15 <= session_minutes <= 120 or not 5 <= idle_minutes <= 30:
        raise ValueError("a book session is 15-120 minutes with 5-30 idle")
    if idle_minutes >= session_minutes or not 1 <= questions <= 50:
        raise ValueError("idle must be shorter than the session; 1-50 questions")


class DocBookSessions(ClosingStore):
    def __init__(
        self,
        docs: Docs,
        keyring: Keyring,
        *,
        prefix: str = "jarvis_",
        session_minutes: int = 45,
        idle_minutes: int = 10,
        questions: int = 20,
    ) -> None:
        _check_limits(session_minutes, idle_minutes, questions)
        self._docs, self._ring, self._coll = docs, keyring, f"{prefix}book_sessions"
        self._notes = f"{prefix}book_notices"
        self._session = timedelta(minutes=session_minutes)
        self._idle = timedelta(minutes=idle_minutes)
        self.questions = questions

    def _aad(self, uid: str, bk: str) -> str:
        return f"book/session/{uid}/{bk}/v1"

    # ---- views -----------------------------------------------------------------------------------
    def _view(self, bk: str, doc: dict[str, Any]) -> SessionView:
        try:
            asked = int(doc.get("questions", 0))
            return SessionView(
                session_id=bk,
                audience=doc["audience"],
                created_at=doc["created_at"],
                until=doc["until"],
                idle_until=doc["idle_until"],
                questions=asked,
                questions_left=max(0, self.questions - asked),
                state=doc.get("state", "open"),
            )
        except (KeyError, TypeError, ValueError, ValidationError):
            raise SessionGone(GONE) from None

    # ---- reads -----------------------------------------------------------------------------------
    async def _by_token(self, token: str) -> tuple[str, dict[str, Any]]:
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            raise SessionGone(GONE)
        tag = self._ring.mac(PURPOSE, token)
        rows = await self._docs.query(Query(self._coll, where=("mac", tag), limit=1))
        if not rows:
            raise SessionGone(GONE)
        return rows[0]

    async def _owned(self, uid: str) -> list[tuple[str, dict[str, Any]]]:
        return await self._docs.query(Query(self._coll, where=("uid", uid)))

    async def resolve(self, uid: str, token: str, *, now: datetime) -> SessionView:
        bk, doc = await self._by_token(token)
        if doc.get("uid") != uid or doc.get("state") != "open":
            raise SessionGone(GONE)
        if due(doc, now) is not None:
            closing = await self.close_claim(uid, bk, "expired", now, by_due=True)
            if closing is None:
                raise SessionGone(GONE)
            raise SessionEnded(closing)
        return self._view(bk, doc)

    async def live(self, uid: str, *, now: datetime) -> SessionView | None:
        rows = [
            (bk, d)
            for bk, d in await self._owned(uid)
            if d.get("state") == "open" and due(d, now) is None
        ]
        if not rows:
            return None
        bk, doc = max(rows, key=lambda r: (str(r[1].get("created_at", "")), r[0]))
        return self._view(bk, doc)

    # ---- writes ----------------------------------------------------------------------------------
    def _new_doc(self, uid: str, audience: Audience, token: str, now: datetime) -> dict[str, Any]:
        return {
            "v": 1,
            "uid": uid,
            "audience": audience,
            "mac": self._ring.mac(PURPOSE, token),
            "created_at": now.isoformat(),
            "last_seen": now.isoformat(),
            "until": (now + self._session).isoformat(),
            "idle_until": (now + self._idle).isoformat(),
            "questions": 0,
            "state": "open",
            "reason": None,
            "blob": None,
        }

    async def open(
        self, uid: str, audience: Audience, *, now: datetime
    ) -> tuple[OpenedSession, ClosedSession | None]:
        ended: ClosedSession | None = None  # BookService ends every session first (and tells)
        for bk, doc in await self._owned(uid):
            closing = await self.close_claim(uid, bk, "new_open", now, by_due=True)
            if closing is not None and doc.get("state") == "open" and ended is None:
                ended = closing.closed
        token = secrets.token_urlsafe(TOKEN_BYTES)
        bk = f"bk_{secrets.token_hex(8)}"
        doc = self._new_doc(uid, audience, token, now)
        await self._docs.write([Create(self._path(bk), doc)])
        return OpenedSession(token=token, session=self._view(bk, doc)), ended

    async def beat(self, uid: str, token: str, *, now: datetime) -> SessionView:
        bk = (await self.resolve(uid, token, now=now)).session_id

        async def work(tx: DocTx) -> dict[str, Any]:
            doc = await tx.get(self._path(bk))
            if doc is None or doc.get("uid") != uid or doc.get("state") != "open":
                raise SessionGone(GONE)
            idle = min(now + self._idle, at(doc["until"]))
            new = {**doc, "last_seen": now.isoformat(), "idle_until": idle.isoformat()}
            tx.set(self._path(bk), new)
            return new

        return self._view(bk, await self._docs.transaction(work))

    def _seal(self, uid: str, bk: str, turns: list[list[str]]) -> str:
        plain = json.dumps(turns, ensure_ascii=False).encode("utf-8")
        return self._ring.cipher(PURPOSE).encrypt(plain, aad=self._aad(uid, bk))

    def _unseal(self, uid: str, bk: str, blob: Any) -> list[list[str]]:
        """The sealed turns, each [question, reply, reply id] (the id "" for an older turn)."""
        if not isinstance(blob, str) or not blob:
            return []
        try:
            raw = json.loads(self._ring.cipher(PURPOSE).decrypt(blob, aad=self._aad(uid, bk)))
        except (VaultError, ValueError):
            log.warning("book session turns did not open; starting without them")
            return []
        if not isinstance(raw, list):
            return []
        return [[str(t[0]), str(t[1]), str(t[2]) if len(t) > 2 else ""] for t in raw][-TURNS_KEPT:]

    async def _turn(
        self, uid: str, sid: str, question: str, reply: str, *, count: bool, reply_id: str = ""
    ) -> int:
        async def work(tx: DocTx) -> int:
            doc = await tx.get(self._path(sid))
            if doc is None or doc.get("uid") != uid or doc.get("state") != "open":
                raise SessionGone(GONE)
            turns = [*self._unseal(uid, sid, doc.get("blob")), [question, reply, reply_id]]
            asked = int(doc.get("questions", 0)) + (1 if count else 0)
            blob = self._seal(uid, sid, turns[-TURNS_KEPT:])
            tx.set(self._path(sid), {**doc, "blob": blob, "questions": asked})
            return asked

        return max(0, self.questions - await self._docs.transaction(work))

    async def add_turn(self, uid: str, session_id: str, question: str, reply: str) -> int:
        """ports.BookSessions: store a turn AND count it (the lane reserves first instead)."""
        return await self._turn(uid, session_id, question, reply, count=True)

    async def put_turn(
        self, uid: str, session_id: str, question: str, reply: str, *, reply_id: str = ""
    ) -> int:
        """Store the guarded turn of a question already reserved; the questions left."""
        return await self._turn(uid, session_id, question, reply, count=False, reply_id=reply_id)

    async def reserve(self, uid: str, session_id: str) -> int | None:
        """Count one question BEFORE the model call, atomically: the questions left after it,
        or None at the session's limit (nothing counted). SessionGone when it has closed."""

        async def work(tx: DocTx) -> int | None:
            doc = await tx.get(self._path(session_id))
            if doc is None or doc.get("uid") != uid or doc.get("state") != "open":
                raise SessionGone(GONE)
            asked = int(doc.get("questions", 0))
            if asked >= self.questions:
                return None
            tx.set(self._path(session_id), {**doc, "questions": asked + 1})
            return self.questions - asked - 1

        return await self._docs.transaction(work)

    async def release(self, uid: str, session_id: str) -> None:
        """Give back a reserved question no model answered (No-AI, the limit, a failed call)."""

        async def work(tx: DocTx) -> None:
            doc = await tx.get(self._path(session_id))
            if doc is not None and doc.get("uid") == uid and doc.get("state") == "open":
                asked = max(0, int(doc.get("questions", 0)) - 1)
                tx.set(self._path(session_id), {**doc, "questions": asked})

        await self._docs.transaction(work)

    async def turns(self, uid: str, session_id: str) -> tuple[tuple[str, str], ...]:
        doc = await self._docs.get(self._path(session_id))
        if doc is None or doc.get("uid") != uid or doc.get("state") != "open":
            return ()
        return tuple((q, r) for q, r, _ in self._unseal(uid, session_id, doc.get("blob")))

    async def reply(self, uid: str, session_id: str, reply_id: str) -> str | None:
        """A guarded reply of this open session by its id (the show speaks it by id), or None."""
        doc = await self._docs.get(self._path(session_id))
        if not reply_id or doc is None or doc.get("uid") != uid or doc.get("state") != "open":
            return None
        turns = self._unseal(uid, session_id, doc.get("blob"))
        return next((r for _, r, rid in turns if rid == reply_id), None)

    # ---- close and sweep (closing.ClosingStore does the work) ---------------------------------
    async def close(
        self, uid: str, session_id: str, *, reason: CloseReason, now: datetime
    ) -> ClosedSession:
        """ports.BookSessions. `notified` True: someone else tells (BookService uses
        `close_claim` and tells itself)."""
        closing = await self.close_claim(uid, session_id, reason, now)
        if closing is None:
            raise SessionGone(GONE)
        return closing.closed

    async def sweep(self, *, now: datetime) -> tuple[ClosedSession, ...]:
        """ports.BookSessions: close what is over and recover unfinished closes (nobody tells
        here; BookService.sweep does the same and tells)."""
        out: list[ClosedSession] = []
        for uid, bk in await self.sweep_targets(now=now):
            closing = await self.close_claim(uid, bk, "expired", now, due_only=True)
            out += [closing.closed] if closing is not None else []
        for uid, bk in await self.orphans(now=now):
            closing = await self.claim_orphan(uid, bk, now)
            out += [closing.closed] if closing is not None else []
        return tuple(out)


__all__ = ["GONE", "TURNS_KEPT", "DocBookSessions", "SessionEnded"]
