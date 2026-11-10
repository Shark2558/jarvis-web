# src/jarvis/buildbook/closing.py
"""Closing book sessions, and telling the owner exactly once (R6 D14).

A close is: (1) ONE transaction marks the session `closing`, drops its turns AND writes a
content-free notice record `{prefix}book_notices/{bk}` = {uid, audience, reason, created_at,
closed_at, questions, claim_at, told} that CLAIMS the telling for this caller; (2) the session
document is deleted and read back absent (`wiped`). The caller that holds the claim writes the
audit line and sends the notice (`BookService`), then marks the record `told` (and drops it once
the session is gone). Nobody else tells:

- a second closer of the same session finds it `closing` with an unexpired claim: no claim;
- a closer that died after (1) leaves the claim to expire (`NOTICE_LEASE`); the sweep then claims
  it again, in a transaction, and tells (from the session document, or from the record when the
  document is already gone): recoverable, and still once;
- a delete that failed is retried by the sweep without a second notice (the record says told);
  when it finally succeeds the closing says `late_wipe` (the service writes one audit line).

Nothing here logs a token, a question or a reply.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from pydantic import ValidationError

from jarvis.buildbook.model import ClosedSession, CloseReason
from jarvis.buildbook.ports import BookSessions
from jarvis.logging import get_logger
from jarvis.storage.docs import Delete, Docs, DocTx, Query

log = get_logger(__name__)

NOTICE_LEASE = timedelta(minutes=2)  # a claimed notice not told by then is the sweep's


def at(text: Any) -> datetime:
    return datetime.fromisoformat(str(text))


def due(doc: dict[str, Any], now: datetime) -> CloseReason | None:
    """expired | idle | None (live). A document whose limits can't be read is over."""
    try:
        if now >= at(doc["until"]):
            return "expired"
        return "idle" if now >= at(doc["idle_until"]) else None
    except (KeyError, TypeError, ValueError):
        return "expired"


def closed_from(
    bk: str, doc: dict[str, Any], now: datetime, *, wiped: bool, notified: bool
) -> ClosedSession:
    """`doc` is the session document or its notice record (both hold the same fields)."""
    ended = at(doc.get("closed_at") or now.isoformat())
    return ClosedSession(
        session_id=bk,
        audience=doc["audience"],
        reason=doc["reason"],
        created_at=doc["created_at"],
        closed_at=ended.isoformat(),
        minutes=max(0, int((ended - at(doc["created_at"])).total_seconds() // 60)),
        questions=max(0, int(doc.get("questions", 0))),
        wiped=wiped,
        notified=notified,
    )


@dataclass(frozen=True)
class Closing:
    """One close: `claimed` means THIS caller audits, tells and then calls `told`."""

    uid: str
    closed: ClosedSession
    claimed: bool
    late_wipe: bool = False  # an earlier failed delete has now finished (the owner was told)


def _stale(note: dict[str, Any], now: datetime) -> bool:
    try:
        return now - at(note["claim_at"]) >= NOTICE_LEASE
    except (KeyError, TypeError, ValueError):
        return True


class ClosingStore:
    """The close half of `DocBookSessions` (sessions.py mixes it in)."""

    _docs: Docs
    _coll: str
    _notes: str

    def _path(self, bk: str) -> str:
        return f"{self._coll}/{bk}"

    def _note(self, bk: str) -> str:
        return f"{self._notes}/{bk}"

    @staticmethod
    def _record(uid: str, marked: dict[str, Any], now: datetime) -> dict[str, Any]:
        keep = ("audience", "reason", "created_at", "closed_at", "questions")
        record = {"uid": uid, **{k: marked.get(k) for k in keep}}
        return {**record, "claim_at": now.isoformat(), "told": False}

    async def _mark(
        self, uid: str, bk: str, reason: CloseReason, now: datetime, *, due_only: bool, by_due: bool
    ) -> tuple[dict[str, Any], bool, bool] | None:
        """(the marked document, claimed, told before) or None: nothing of this owner to close."""

        async def work(tx: DocTx) -> tuple[dict[str, Any], bool, bool] | None:
            doc, note = await tx.get(self._path(bk)), await tx.get(self._note(bk))
            if doc is None or doc.get("uid") != uid:
                return None
            if doc.get("state") != "closing":
                why = due(doc, now) if by_due or due_only else None
                if why is None and due_only:
                    return None  # beaten back to life since the sweep looked
                marked = {**doc, "state": "closing", "reason": why or reason, "blob": None}
                marked["closed_at"] = now.isoformat()
                tx.set(self._path(bk), marked)
                tx.set(self._note(bk), self._record(uid, marked, now))
                return marked, True, False
            claim = note is not None and not note.get("told") and _stale(note, now)
            if claim and note is not None:
                tx.set(self._note(bk), {**note, "claim_at": now.isoformat()})
            return doc, claim, note is None or bool(note.get("told"))

        return await self._docs.transaction(work)

    async def _delete(self, path: str) -> bool:
        try:
            await self._docs.write([Delete(path)])
            return await self._docs.get(path) is None
        except Exception as exc:  # noqa: BLE001 - the sweep retries; the turns are already gone
            log.warning("book session delete failed", extra={"error": type(exc).__name__})
            return False

    async def close_claim(
        self,
        uid: str,
        bk: str,
        reason: CloseReason,
        now: datetime,
        *,
        due_only: bool = False,
        by_due: bool = False,
    ) -> Closing | None:
        """D14 steps 1-2 for one session of `uid`; None when there is nothing to close.
        `by_due`: a session already over says so (expired / idle: "ended by itself") whatever
        ended it now (a new open, Resume, Privacy); `due_only`: close it only if it is over."""
        got = await self._mark(uid, bk, reason, now, due_only=due_only, by_due=by_due)
        if got is None:
            return None
        doc, claimed, told_before = got
        wiped = await self._delete(self._path(bk))
        try:
            closed = closed_from(bk, doc, now, wiped=wiped, notified=not claimed)
        except (KeyError, TypeError, ValueError, ValidationError):
            return None  # a malformed document: deleted, nothing to report
        late = wiped and told_before and not claimed
        return Closing(uid, closed, claimed=claimed, late_wipe=late)

    async def told(self, uid: str, bk: str, *, wiped: bool) -> None:
        """The claimed notice went out: never again. The record goes once the session is gone."""

        async def work(tx: DocTx) -> None:
            note = await tx.get(self._note(bk))
            if note is not None and note.get("uid") == uid:
                tx.set(self._note(bk), {**note, "told": True})

        try:
            await self._docs.transaction(work)
        except Exception as exc:  # noqa: BLE001 - at worst the sweep tells once more
            log.error("book notice not marked told", extra={"error": type(exc).__name__})
            return
        if wiped:
            await self._delete(self._note(bk))

    # ---- what the sweep and the owner-wide closes walk ------------------------------------------
    async def owned_ids(self, uid: str) -> list[str]:
        return [bk for bk, _ in await self._docs.query(Query(self._coll, where=("uid", uid)))]

    async def sweep_targets(self, *, now: datetime) -> list[tuple[str, str]]:
        """(uid, bk) of every session that is over (expired, idle) or still `closing`."""
        out: list[tuple[str, str]] = []
        for bk, doc in await self._docs.query(Query(self._coll)):
            uid = doc.get("uid")
            if not isinstance(uid, str):
                await self._delete(self._path(bk))  # malformed: nobody's session, just remove it
            elif doc.get("state") == "closing" or due(doc, now) is not None:
                out.append((uid, bk))
        return out

    async def orphans(self, *, now: datetime) -> list[tuple[str, str]]:
        """(uid, bk) of claimed notices nobody told whose session is already gone; told records
        of gone sessions are dropped here."""
        out: list[tuple[str, str]] = []
        for bk, note in await self._docs.query(Query(self._notes)):
            if await self._docs.get(self._path(bk)) is not None:
                continue  # close_claim handles a session that is still there
            if note.get("told") or not isinstance(note.get("uid"), str):
                await self._delete(self._note(bk))
            elif _stale(note, now):
                out.append((str(note["uid"]), bk))
        return out

    async def claim_orphan(self, uid: str, bk: str, now: datetime) -> Closing | None:
        async def work(tx: DocTx) -> dict[str, Any] | None:
            note, doc = await tx.get(self._note(bk)), await tx.get(self._path(bk))
            if note is None or doc is not None or note.get("uid") != uid:
                return None
            if note.get("told") or not _stale(note, now):
                return None
            tx.set(self._note(bk), {**note, "claim_at": now.isoformat()})
            return note

        note = await self._docs.transaction(work)
        if note is None:
            return None
        try:
            closed = closed_from(bk, note, now, wiped=True, notified=False)
        except (KeyError, TypeError, ValueError, ValidationError):
            await self._delete(self._note(bk))
            return None
        return Closing(uid, closed, claimed=True)


class Sweeping(BookSessions, Protocol):
    """`ports.BookSessions` plus the close half of `DocBookSessions` (closing.ClosingStore)."""

    async def close_claim(
        self,
        uid: str,
        bk: str,
        reason: CloseReason,
        now: datetime,
        *,
        due_only: bool = False,
        by_due: bool = False,
    ) -> Closing | None: ...

    async def told(self, uid: str, bk: str, *, wiped: bool) -> None: ...

    async def owned_ids(self, uid: str) -> list[str]: ...

    async def sweep_targets(self, *, now: datetime) -> list[tuple[str, str]]: ...

    async def orphans(self, *, now: datetime) -> list[tuple[str, str]]: ...

    async def claim_orphan(self, uid: str, bk: str, now: datetime) -> Closing | None: ...


__all__ = ["NOTICE_LEASE", "Closing", "ClosingStore", "Sweeping", "at", "closed_from", "due"]
