# src/jarvis/storage/sessions.py
"""SessionStore on the Docs port (Firestore in prod).

Layout:  {prefix}sessions/{sid}               header: user_id, updated_at, turn_count, rev,
                                                title, json(session without turns)
         {prefix}sessions/{sid}/turns/{000001} one doc per turn (no 1 MiB ceiling per chat)

Turns are append-only, so save() writes only new/changed turns plus the header, header LAST
(a reader never sees a header that points at turns not yet written). get() costs one read when
the in-process copy is current (`rev` matches), so steady-state chat stays far inside the free
quota. Conversations are kept until the owner deletes them (no TTL: TTL deletes are billed).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import OrderedDict
from dataclasses import dataclass

from jarvis.core.models import Session, SessionSummary, session_title
from jarvis.logging import get_logger
from jarvis.memory.base import SessionStore
from jarvis.storage.docs import Delete, Docs, IndexNotReady, Op, Query, Set

log = get_logger(__name__)

SAFE_ID = re.compile(r"(?!__.*__\Z)[A-Za-z0-9_-]{1,128}")  # also a valid Firestore doc id
CACHE_SESSIONS = 64
PING_TTL_S = 60.0
LIST_FALLBACK_SCAN = 500


def safe_id(value: str) -> bool:
    return SAFE_ID.fullmatch(value) is not None


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:32]


@dataclass(frozen=True)
class _Known:
    rev: str
    session: Session
    turn_digests: tuple[str, ...]


class DocSessionStore(SessionStore):
    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self._d = docs
        self._col = f"{prefix}sessions"
        self._ping_path = f"{prefix}meta/ping"
        self._known: OrderedDict[str, _Known] = OrderedDict()
        self._ping: tuple[float, bool] | None = None  # (checked_at, ok)

    def _header(self, sid: str) -> str:
        return f"{self._col}/{sid}"

    def _turn(self, sid: str, index: int) -> str:
        return f"{self._col}/{sid}/turns/{index + 1:06d}"

    def _remember(self, k: _Known) -> None:
        self._known[k.session.id] = k
        self._known.move_to_end(k.session.id)
        while len(self._known) > CACHE_SESSIONS:
            self._known.popitem(last=False)

    async def get(self, session_id: str) -> Session | None:
        if not safe_id(session_id):
            return None
        header = await self._d.get(self._header(session_id))
        if header is None:
            self._known.pop(session_id, None)
            return None
        known = self._known.get(session_id)
        if known is not None and known.rev == header.get("rev"):
            self._known.move_to_end(session_id)
            return known.session.model_copy(deep=True)
        try:
            count = int(header["turn_count"])
            base = json.loads(header["json"])
            rows = await self._d.query(Query(f"{self._col}/{session_id}/turns", limit=count))
            turn_jsons = [str(d["json"]) for _, d in rows]
            session = Session.model_validate({**base, "turns": [json.loads(j) for j in turn_jsons]})
        except (KeyError, TypeError, ValueError) as exc:
            log.error(
                "unreadable session document",
                extra={"session_id": session_id, "error": type(exc).__name__},
            )
            return None
        if len(turn_jsons) != count:
            log.error(
                "session is missing turns",
                extra={"session_id": session_id, "expected": count, "found": len(turn_jsons)},
            )
        contiguous = [tid for tid, _ in rows] == [f"{i + 1:06d}" for i in range(count)]
        if contiguous:
            self._remember(
                _Known(str(header.get("rev", "")), session, tuple(_digest(j) for j in turn_jsons))
            )
        else:  # never trust positions read across a gap: the next save rewrites every turn
            self._known.pop(session_id, None)
        return session.model_copy(deep=True)

    async def save(self, session: Session) -> None:
        if not safe_id(session.id):
            raise ValueError("invalid session id")
        turn_jsons = [t.model_dump_json() for t in session.turns]
        digests = tuple(_digest(j) for j in turn_jsons)
        header_json = session.model_dump_json(exclude={"turns"})
        rev = _digest(header_json + "".join(digests))
        known = self._known.get(session.id)
        if known is not None and known.rev == rev:
            return  # nothing changed since we last read or wrote it
        prior = known.turn_digests if known else ()
        ops: list[Op] = [
            Set(self._turn(session.id, i), {"json": j})
            for i, j in enumerate(turn_jsons)
            if i >= len(prior) or prior[i] != digests[i]
        ]
        ops += [Delete(self._turn(session.id, i)) for i in range(len(digests), len(prior))]
        ops.append(
            Set(
                self._header(session.id),
                {
                    "user_id": session.user_id,
                    "created_at": session.created_at,
                    "updated_at": session.updated_at,
                    "turn_count": len(turn_jsons),
                    "total_cost_usd": session.total_cost_usd,
                    "title": session_title(session),
                    "rev": rev,
                    "json": header_json,
                },
            )
        )
        await self._d.write(ops)
        self._remember(_Known(rev, session.model_copy(deep=True), digests))

    async def delete(self, session_id: str) -> bool:
        if not safe_id(session_id) or await self._d.get(self._header(session_id)) is None:
            return False
        turns = await self._d.query(Query(f"{self._col}/{session_id}/turns"))
        # header LAST: if a long delete is interrupted the conversation is still listed (with
        # fewer turns) and the owner can simply delete it again; no private text is orphaned
        ops: list[Op] = [Delete(f"{self._col}/{session_id}/turns/{tid}") for tid, _ in turns]
        ops.append(Delete(self._header(session_id)))
        self._known.pop(session_id, None)
        await self._d.write(ops)
        self._known.pop(session_id, None)
        return True

    async def list_for_user(self, user_id: str, limit: int = 50) -> list[SessionSummary]:
        try:
            rows = await self._d.query(
                Query(
                    self._col,
                    where=("user_id", user_id),
                    order_by="updated_at",
                    descending=True,
                    limit=limit,
                )
            )
        except IndexNotReady:
            log.warning("sessions index not ready; sorting in the app meanwhile")
            rows = await self._d.query(
                Query(self._col, where=("user_id", user_id), limit=LIST_FALLBACK_SCAN)
            )
            rows.sort(key=lambda r: r[1].get("updated_at"), reverse=True)  # type: ignore[arg-type,return-value]
            rows = rows[:limit]
        out: list[SessionSummary] = []
        for sid, h in rows:
            try:
                out.append(
                    SessionSummary(
                        id=sid,
                        user_id=h["user_id"],
                        created_at=h["created_at"],
                        updated_at=h["updated_at"],
                        turn_count=int(h["turn_count"]),
                        total_cost_usd=float(h.get("total_cost_usd", 0.0)),
                        title=str(h.get("title", "")),
                    )
                )
            except (KeyError, TypeError, ValueError):
                log.error("unreadable session header", extra={"session_id": sid})
        return out

    async def ping(self) -> bool:
        if self._ping is not None and time.monotonic() - self._ping[0] < PING_TTL_S:
            return self._ping[1]
        try:
            await self._d.get(self._ping_path)
            ok = True
        except Exception as exc:  # noqa: BLE001 — health reports, never raises
            log.error("session store ping failed", extra={"error": type(exc).__name__})
            ok = False
        self._ping = (time.monotonic(), ok)
        return ok

    async def close(self) -> None:
        await self._d.close()
