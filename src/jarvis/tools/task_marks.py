# src/jarvis/tools/task_marks.py
"""To-dos JARVIS wrote from outside content (slice 11 D8, security review of A+B; Layer 7).

A Google to-do has no private field JARVIS can tag, so when JARVIS writes one from other people's
words — a round that had read a mail, a web page, a document, someone else's event, or a card
proposed in such a round and then approved — its id goes into the owner's set here, and
`provenance.is_owner_authored_task` refuses it: a later look-up that returns it is untrusted, and
so a write after it is a card. The text the owner approved on the card stays someone else's.

Layout:  {prefix}outside_tasks/{user_id}   ids: [task id, …]
                                            pending: {token: ISO time}

Fail closed at every step:
- an existing to-do (update) is marked BEFORE it is changed; no mark → no change;
- a new to-do (add, restore) gets a pending token BEFORE it is made (no token → nothing made),
  and its id replaces the token after. If the insert itself fails the token is dropped (best
  effort) — unless Google may have made it anyway (`GoogleUncertain`), when it stays. If the
  second write fails the token stays too, and every to-do Google changed since a few minutes
  before it counts as outside (`OutsideSet`) — the new one among them. After `PENDING_TTL`
  `read` ignores a token and the scheduler tick prunes it (`sweep`), so one failure never
  taints every later to-do for good;
- a set that can't be read (or a malformed one) makes every to-do count as outside.
At most `MAX_IDS` ids: past that a mark fails, which fails the write that needed it.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from jarvis.integrations.google import GoogleUncertain
from jarvis.logging import get_logger
from jarvis.storage.docs import Docs, DocTx
from jarvis.tools.provenance import is_owner_authored_task
from jarvis.undo.store import owner_ok

log = get_logger(__name__)

MAX_IDS = 20_000
PENDING_MARGIN = timedelta(minutes=5)  # Google's clock may run behind ours
PENDING_TTL = timedelta(hours=1)  # an unfinished mark stops counting (and is pruned) after this
SWEEP_OWNERS = 100  # owners one tick looks at


def utcnow() -> datetime:
    return datetime.now(UTC)


def _when(value: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


@dataclass(frozen=True)
class OutsideSet:
    """The owner's outside to-dos as read now: their ids, and since when a mark is unfinished."""

    ids: frozenset[str]
    pending_since: datetime | None = None

    def owner_authored(self, task: Mapping[str, Any]) -> bool:
        """The provenance rule plus this set: a marked id — or, while a mark is unfinished, any
        to-do Google changed since then (or without a readable `updated`) — is not his own."""
        if not is_owner_authored_task(task, outside=self.ids):
            return False
        if self.pending_since is None:
            return True
        updated = _when(task.get("updated"))
        return updated is not None and updated < self.pending_since


def owner_authored_task(task: Any, marks: OutsideSet | None) -> bool:
    """`OutsideSet.owner_authored`, where an unreadable set (None) means no to-do is his own."""
    return marks is not None and isinstance(task, Mapping) and marks.owner_authored(task)


def _decode(doc: Mapping[str, Any] | None) -> tuple[list[str], dict[str, str]]:
    if doc is None:
        return [], {}
    ids, pending = doc.get("ids", []), doc.get("pending", {})
    if not isinstance(ids, list) or not isinstance(pending, dict):
        raise ValueError("malformed outside-to-do set")
    return [str(i) for i in ids], {str(k): str(v) for k, v in pending.items()}


class OutsideTasks:
    def __init__(
        self, docs: Docs, *, prefix: str = "jarvis_", clock: Callable[[], datetime] = utcnow
    ) -> None:
        self._d = docs
        self._col = f"{prefix}outside_tasks"
        self._clock = clock

    def _path(self, uid: str) -> str:
        if not owner_ok(uid):
            raise ValueError("no owner for the outside to-do set")
        return f"{self._col}/{uid}"

    async def read(self, uid: str) -> OutsideSet | None:
        """The set now; None when it can't be read (callers: no to-do is the owner's own)."""
        try:
            ids, pending = _decode(await self._d.get(self._path(uid)))
            now = self._clock()
            times = [t for v in pending.values() if not self._expired(t := _when(v), now)]
        except Exception as exc:  # noqa: BLE001 — unreadable: fail closed, never raise
            log.error("outside to-do set unreadable", extra={"error": type(exc).__name__})
            return None
        if any(t is None for t in times):
            return OutsideSet(frozenset(ids), datetime.min.replace(tzinfo=UTC))
        since = min((t for t in times if t is not None), default=None)
        return OutsideSet(frozenset(ids), since - PENDING_MARGIN if since else None)

    @staticmethod
    def _expired(since: datetime | None, now: datetime) -> bool:
        """A readable token older than `PENDING_TTL` (an unreadable one never expires: closed)."""
        return since is not None and now - since >= PENDING_TTL

    async def _change(
        self, uid: str, add: Iterable[str], token: str | None, drop: str | None
    ) -> None:
        path = self._path(uid)
        new = [i for i in add if i]
        at = self._clock().astimezone(UTC).isoformat()

        async def fn(tx: DocTx) -> None:
            ids, pending = _decode(await tx.get(path))
            merged = ids + [i for i in new if i not in ids]
            if len(merged) > MAX_IDS:
                raise RuntimeError("too many outside to-dos to remember")
            if token is not None:
                pending[token] = at
            if drop is not None:
                pending.pop(drop, None)
            tx.set(path, {"user_id": uid, "ids": merged, "pending": pending})

        await self._d.transaction(fn)

    async def add(self, uid: str, task_ids: Iterable[str]) -> None:
        """Mark existing to-dos (before they change). Raises when the mark can't be stored."""
        await self._change(uid, task_ids, None, None)

    async def begin(self, uid: str) -> str:
        """Before a to-do is made: a pending token (raises when it can't be stored)."""
        token = secrets.token_hex(8)
        await self._change(uid, (), token, None)
        return token

    async def failed(self, uid: str, token: str, exc: Exception) -> None:
        """The make raised `exc`. Unless Google may have made the to-do anyway
        (`GoogleUncertain`: no answer, a 5xx), nothing exists: drop the token. Best effort —
        logged, never raised, so it can't mask `exc`. An uncertain make keeps the token (fail
        closed) until it expires."""
        if isinstance(exc, GoogleUncertain):
            return
        try:
            await self._change(uid, (), None, token)
        except Exception as err:  # noqa: BLE001
            log.error("pending to-do mark not dropped", extra={"error": type(err).__name__})

    async def sweep(self, owners: Sequence[str]) -> int:
        """Prune expired pending tokens of up to `SWEEP_OWNERS` owners; returns how many went.
        Housekeeping: never raises, one owner never blocks another."""
        gone = 0
        for uid in list(owners)[:SWEEP_OWNERS]:
            try:
                gone += await self._prune(uid)
            except Exception as exc:  # noqa: BLE001
                log.warning("outside to-do sweep failed", extra={"error": type(exc).__name__})
        return gone

    async def _prune(self, uid: str) -> int:
        path = self._path(uid)
        now = self._clock()

        async def fn(tx: DocTx) -> int:
            ids, pending = _decode(await tx.get(path))
            kept = {k: v for k, v in pending.items() if not self._expired(_when(v), now)}
            if len(kept) != len(pending):
                tx.set(path, {"user_id": uid, "ids": ids, "pending": kept})
            return len(pending) - len(kept)

        return int(await self._d.transaction(fn))

    async def finish(self, uid: str, token: str, task_ids: Iterable[str]) -> None:
        """After: the new ids replace the token. A failure keeps the token (fail closed) and is
        logged, never raised — the to-do exists and the caller's result says so."""
        try:
            await self._change(uid, task_ids, None, token)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "outside to-do mark unfinished; recent to-dos count as outside",
                extra={"error": type(exc).__name__},
            )


__all__ = ["MAX_IDS", "OutsideSet", "OutsideTasks", "owner_authored_task"]
