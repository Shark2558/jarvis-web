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

Close (D14 steps 1-2): mark `closing` and drop the turns in the same write, delete the document,
read it back absent -> `wiped`. A failed delete leaves a turn-less `closing` document that no token
opens and the sweep finishes later; such a retry comes back with `notified=True` ("already told").
Nothing here logs a token, a question or a reply.
"""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timedelta
from typing import Any

from pydantic import ValidationError

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
from jarvis.storage.docs import Create, Delete, Docs, DocTx, Query

log = get_logger(__name__)

PURPOSE = "book_session"
TURNS_KEPT = 8  # D11: the talk lane's context is this session's last 8 turns
TOKEN_BYTES = 32
_TOKEN = re.compile(r"^[A-Za-z0-9_\-]{43,128}$")
GONE = "This build book session has ended. Open the book again from the console."


class SessionEnded(SessionGone):
    """The session was expired or idle and has just been closed (the caller tells the owner)."""

    def __init__(self, closed: ClosedSession) -> None:
        self.closed = closed
        super().__init__(GONE)


def _check_limits(session_minutes: int, idle_minutes: int, questions: int) -> None:
    if not 15 <= session_minutes <= 120 or not 5 <= idle_minutes <= 30:
        raise ValueError("a book session is 15-120 minutes with 5-30 idle")
    if idle_minutes >= session_minutes or not 1 <= questions <= 50:
        raise ValueError("idle must be shorter than the session; 1-50 questions")


def _at(text: Any) -> datetime:
    return datetime.fromisoformat(str(text))


class DocBookSessions:
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
        self._session = timedelta(minutes=session_minutes)
        self._idle = timedelta(minutes=idle_minutes)
        self.questions = questions

    def _path(self, bk: str) -> str:
        return f"{self._coll}/{bk}"

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

    @staticmethod
    def _due(doc: dict[str, Any], now: datetime) -> CloseReason | None:
        try:
            if now >= _at(doc["until"]):
                return "expired"
            return "idle" if now >= _at(doc["idle_until"]) else None
        except (KeyError, TypeError, ValueError):
            return "expired"  # a document we can't read the limits of is over

    def _closed(
        self, bk: str, doc: dict[str, Any], now: datetime, *, wiped: bool, retry: bool
    ) -> ClosedSession:
        created = _at(doc["created_at"])
        return ClosedSession(
            session_id=bk,
            audience=doc["audience"],
            reason=doc["reason"],
            created_at=doc["created_at"],
            closed_at=now.isoformat(),
            minutes=max(0, int((now - created).total_seconds() // 60)),
            questions=max(0, int(doc.get("questions", 0))),
            wiped=wiped,
            notified=retry,
        )

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
        reason = self._due(doc, now)
        if reason is not None:
            closed = await self._close_doc(uid, bk, reason, now)
            if closed is None:
                raise SessionGone(GONE)
            raise SessionEnded(closed)
        return self._view(bk, doc)

    async def live(self, uid: str, *, now: datetime) -> SessionView | None:
        rows = [
            (bk, d)
            for bk, d in await self._owned(uid)
            if d.get("state") == "open" and self._due(d, now) is None
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
        ended: ClosedSession | None = None
        for bk, doc in await self._owned(uid):
            was_open = doc.get("state") == "open"
            closed = await self._close_doc(uid, bk, "new_open", now)
            if was_open and ended is None:
                ended = closed
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
            idle = min(now + self._idle, _at(doc["until"]))
            new = {**doc, "last_seen": now.isoformat(), "idle_until": idle.isoformat()}
            tx.set(self._path(bk), new)
            return new

        return self._view(bk, await self._docs.transaction(work))

    def _seal(self, uid: str, bk: str, turns: list[list[str]]) -> str:
        plain = json.dumps(turns, ensure_ascii=False).encode("utf-8")
        return self._ring.cipher(PURPOSE).encrypt(plain, aad=self._aad(uid, bk))

    def _unseal(self, uid: str, bk: str, blob: Any) -> list[list[str]]:
        if not isinstance(blob, str) or not blob:
            return []
        try:
            raw = json.loads(self._ring.cipher(PURPOSE).decrypt(blob, aad=self._aad(uid, bk)))
        except (VaultError, ValueError):
            log.warning("book session turns did not open; starting without them")
            return []
        return [[str(q), str(r)] for q, r in raw][-TURNS_KEPT:] if isinstance(raw, list) else []

    async def add_turn(self, uid: str, session_id: str, question: str, reply: str) -> int:
        async def work(tx: DocTx) -> int:
            doc = await tx.get(self._path(session_id))
            if doc is None or doc.get("uid") != uid or doc.get("state") != "open":
                raise SessionGone(GONE)
            turns = [*self._unseal(uid, session_id, doc.get("blob")), [question, reply]]
            asked = int(doc.get("questions", 0)) + 1
            blob = self._seal(uid, session_id, turns[-TURNS_KEPT:])
            tx.set(self._path(session_id), {**doc, "blob": blob, "questions": asked})
            return asked

        return max(0, self.questions - await self._docs.transaction(work))

    async def turns(self, uid: str, session_id: str) -> tuple[tuple[str, str], ...]:
        doc = await self._docs.get(self._path(session_id))
        if doc is None or doc.get("uid") != uid or doc.get("state") != "open":
            return ()
        return tuple((q, r) for q, r in self._unseal(uid, session_id, doc.get("blob")))

    # ---- close and sweep -------------------------------------------------------------------------
    async def _delete(self, path: str) -> bool:
        try:
            await self._docs.write([Delete(path)])
            return await self._docs.get(path) is None
        except Exception as exc:  # noqa: BLE001 - the sweep retries; the turns are already gone
            log.warning("book session delete failed", extra={"error": type(exc).__name__})
            return False

    async def _close_doc(
        self, uid: str, bk: str, reason: CloseReason, now: datetime
    ) -> ClosedSession | None:
        async def mark(tx: DocTx) -> tuple[dict[str, Any], bool] | None:
            doc = await tx.get(self._path(bk))
            if doc is None or doc.get("uid") != uid:
                return None
            retry = doc.get("state") == "closing"
            marked = {**doc, "state": "closing", "reason": doc.get("reason") or reason}
            tx.set(self._path(bk), {**marked, "blob": None})
            return marked, retry

        got = await self._docs.transaction(mark)
        if got is None:
            return None
        doc, retry = got
        wiped = await self._delete(self._path(bk))
        try:
            return self._closed(bk, doc, now, wiped=wiped, retry=retry)
        except (KeyError, TypeError, ValueError, ValidationError):
            return None  # a malformed document: deleted, nothing to report

    async def close(
        self, uid: str, session_id: str, *, reason: CloseReason, now: datetime
    ) -> ClosedSession:
        closed = await self._close_doc(uid, session_id, reason, now)
        if closed is None:
            raise SessionGone(GONE)
        return closed

    async def sweep_owned(self, *, now: datetime) -> tuple[tuple[str, ClosedSession], ...]:
        """`sweep` with each closed session's owner (the service tells him)."""
        out: list[tuple[str, ClosedSession]] = []
        for bk, doc in await self._docs.query(Query(self._coll)):
            uid = doc.get("uid")
            closing = doc.get("state") == "closing"
            reason = doc.get("reason") if closing else self._due(doc, now)
            if not isinstance(uid, str):
                await self._delete(self._path(bk))  # malformed: nobody's session, just remove it
                continue
            if reason is None:
                continue
            closed = await self._close_doc(uid, bk, reason, now)
            if closed is not None:
                out.append((uid, closed))
        return tuple(out)

    async def sweep(self, *, now: datetime) -> tuple[ClosedSession, ...]:
        return tuple(closed for _, closed in await self.sweep_owned(now=now))


__all__ = ["GONE", "TURNS_KEPT", "DocBookSessions", "SessionEnded"]
