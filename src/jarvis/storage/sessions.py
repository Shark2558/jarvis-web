# src/jarvis/storage/sessions.py
"""SessionStore on the Docs port (Firestore in prod).

Layout:  {prefix}sessions/{sid}               header: user_id, updated_at, turn_count, rev,
                                                title, json(session without turns)
         {prefix}sessions/{sid}/turns/{000001} one doc per turn (no 1 MiB ceiling per chat)

Turns are append-only, so save() writes only new/changed turns plus the header, header LAST
(a reader never sees a header that points at turns not yet written). get() costs one read when
the in-process copy is current (`rev` matches), so steady-state chat stays far inside the free
quota. Conversations are kept until the owner deletes them (no TTL: TTL deletes are billed).

Two processes, one conversation (slice 10 A3): every Session copy carries the `rev` it was read
at or last saved as (`_store_mark`, never serialised). save() is a compare-and-set: inside one
transaction it reads the header and writes only if the stored `rev` is still that one (+1 read
per save; an unchanged session still costs nothing). If another writer got there first, the
stored conversation is reloaded and this save re-applied when it is still consistent — the other
side changed only the header (owner id, settings), or the stored turns are this copy's own (a
commit whose answer was lost). Otherwise — the other side added turns, or deleted the
conversation — `SessionConflict` is raised and nothing is written.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from jarvis.core.models import Session, SessionSummary, session_title
from jarvis.logging import get_logger
from jarvis.memory.base import SessionConflict, SessionStore
from jarvis.storage.docs import Delete, Docs, DocTx, IndexNotReady, Op, Query, Set

log = get_logger(__name__)

SAFE_ID = re.compile(r"(?!__.*__\Z)[A-Za-z0-9_-]{1,128}")  # also a valid Firestore doc id
CACHE_SESSIONS = 64
PING_TTL_S = 60.0
LIST_FALLBACK_SCAN = 500
CAS_ATTEMPTS = 3  # a merge needs a fresh read; a third writer in that window is a real conflict


def safe_id(value: str) -> bool:
    return SAFE_ID.fullmatch(value) is not None


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:32]


@dataclass(frozen=True)
class _Mark:
    """Where a Session copy came from: the stored `rev`, the stored turns' digests at that rev
    (() = unknown, so every turn is rewritten) and the stored header fields this writer may
    change, so a conflict can tell this writer's changes from another's."""

    rev: str
    digests: tuple[str, ...]
    turns: int
    user_id: str
    metadata: str  # canonical JSON


@dataclass(frozen=True)
class _Known:
    mark: _Mark
    session: Session


@dataclass(frozen=True)
class _Plan:
    """What a save writes for one session: its turn JSON, their digests, header JSON and rev."""

    turn_jsons: tuple[str, ...]
    digests: tuple[str, ...]
    header_json: str
    rev: str


class _Moved(Exception):
    """The stored header is not at the revision this save was based on."""


def _meta_json(metadata: dict[str, Any]) -> str:
    return json.dumps(metadata, sort_keys=True, default=str)


def _rev(header: dict[str, Any] | None) -> str | None:
    """The stored revision (None: no conversation stored under that id)."""
    if not isinstance(header, dict):
        return None
    return str(header.get("rev", ""))


def _mark_of(session: Session) -> _Mark | None:
    mark = session._store_mark
    return mark if isinstance(mark, _Mark) else None


def _plan(session: Session) -> _Plan:
    turn_jsons = tuple(t.model_dump_json() for t in session.turns)
    digests = tuple(_digest(j) for j in turn_jsons)
    header_json = session.model_dump_json(exclude={"turns"})
    return _Plan(turn_jsons, digests, header_json, _digest(header_json + "".join(digests)))


def _merged_metadata(
    base: dict[str, Any], ours: dict[str, Any], theirs: dict[str, Any]
) -> dict[str, Any]:
    """Theirs, plus every key this writer added, changed or removed since `base`."""
    out = dict(theirs)
    for key, value in ours.items():
        if key not in base or base[key] != value:
            out[key] = value
    for key in base:
        if key not in ours:
            out.pop(key, None)
    return out


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

    @staticmethod
    def _copy(k: _Known) -> Session:
        out = k.session.model_copy(deep=True)
        out._store_mark = k.mark
        return out

    async def get(self, session_id: str) -> Session | None:
        if not safe_id(session_id):
            return None
        header = await self._d.get(self._header(session_id))
        if header is None:
            self._known.pop(session_id, None)
            return None
        known = self._known.get(session_id)
        if known is not None and known.mark.rev == header.get("rev"):
            self._known.move_to_end(session_id)
            return self._copy(known)
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
        # never trust positions read across a gap: digests () make the next save rewrite all
        digests = tuple(_digest(j) for j in turn_jsons) if contiguous else ()
        mark = _Mark(
            str(header.get("rev", "")),
            digests,
            len(session.turns),
            session.user_id,
            _meta_json(session.metadata),
        )
        known = _Known(mark, session)
        if contiguous:
            self._remember(known)
        else:
            self._known.pop(session_id, None)
        return self._copy(known)

    async def save(self, session: Session) -> None:
        """Compare-and-set (see the module docstring). Raises SessionConflict, writing nothing,
        when another writer changed the conversation in a way this save can't be merged with.
        On a consistent merge the caller's `session` takes the other writer's header changes."""
        if not safe_id(session.id):
            raise ValueError("invalid session id")
        for _ in range(CAS_ATTEMPTS):
            plan, mark = _plan(session), _mark_of(session)
            if mark is not None and mark.rev == plan.rev:
                return  # nothing changed since we last read or wrote it
            try:
                await self._commit(session, plan, mark)
            except _Moved:
                await self._rebase(session, mark)
                continue
            meta = _meta_json(session.metadata)
            saved = _Mark(plan.rev, plan.digests, len(plan.digests), session.user_id, meta)
            session._store_mark = saved
            self._remember(_Known(saved, session.model_copy(deep=True)))
            return
        log.warning("session save lost the race repeatedly", extra={"session_id": session.id})
        raise SessionConflict("This conversation keeps changing in another window.")

    async def _commit(self, session: Session, plan: _Plan, mark: _Mark | None) -> None:
        """The changed turns + the header in one transaction that first checks the stored rev.
        Firestore commits hold ≤ MAX_BATCH writes: a save changing more turns than that (only
        the first save of a long conversation, or a full rewrite) checks the rev, then writes its
        OLDEST turns ahead of the checked commit — history every copy agrees on."""
        sid = session.id
        prior = mark.digests if mark else ()
        ops: list[Op] = [
            Set(self._turn(sid, i), {"json": j})
            for i, j in enumerate(plan.turn_jsons)
            if i >= len(prior) or prior[i] != plan.digests[i]
        ]
        ops += [Delete(self._turn(sid, i)) for i in range(len(plan.digests), len(prior))]
        ops.append(Set(self._header(sid), self._header_doc(session, plan)))
        expected = mark.rev if mark else None
        cut = max(0, len(ops) - self._d.MAX_BATCH)
        if cut:
            if _rev(await self._d.get(self._header(sid))) != expected:
                raise _Moved  # never pre-write into a conversation that moved or was deleted
            await self._d.write(ops[:cut])
        checked = ops[cut:]

        async def fn(tx: DocTx) -> None:
            if _rev(await tx.get(self._header(sid))) != expected:
                raise _Moved
            for op in checked:
                if isinstance(op, Delete):
                    tx.delete(op.path)
                else:
                    tx.set(op.path, op.data)

        await self._d.transaction(fn)

    @staticmethod
    def _header_doc(session: Session, plan: _Plan) -> dict[str, Any]:
        return {
            "user_id": session.user_id,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "turn_count": len(plan.turn_jsons),
            "total_cost_usd": session.total_cost_usd,
            "title": session_title(session),
            "rev": plan.rev,
            "json": plan.header_json,
        }

    async def _rebase(self, session: Session, mark: _Mark | None) -> None:
        """Another writer saved first. Re-apply this save on the stored version if consistent:
        the stored turns are a prefix of ours (nobody else added a turn) and none of the turns
        we were based on is gone. Mutates `session`'s header fields and mark; else raises."""
        stored = await self.get(session.id)
        if stored is None:
            raise SessionConflict("This conversation was deleted in another window.")
        theirs = tuple(_digest(t.model_dump_json()) for t in stored.turns)  # same JSON as ours
        ours = tuple(_digest(t.model_dump_json()) for t in session.turns)
        based_on = mark.turns if mark else 0
        if len(theirs) < based_on or ours[: len(theirs)] != theirs:
            log.warning(
                "session changed elsewhere; not overwriting",
                extra={"session_id": session.id, "ours": len(ours), "theirs": len(theirs)},
            )
            raise SessionConflict("This conversation changed in another window.")
        # without a mark this copy's base is unknown: its header fields are the caller's intent
        base_meta = json.loads(mark.metadata) if mark else stored.metadata
        session.metadata = _merged_metadata(base_meta, session.metadata, stored.metadata)
        if mark is not None and session.user_id == mark.user_id:
            session.user_id = stored.user_id
        session.updated_at = max(session.updated_at, stored.updated_at)
        session._store_mark = stored._store_mark
        log.info("session re-applied on a newer revision", extra={"session_id": session.id})

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
