# src/jarvis/storage/audit.py
"""AuditTrail on the Docs port: the hash chain survives restarts and never forks.

Layout:  {prefix}audit/{seq:012d}   seq, json(AuditEntry)
         {prefix}meta/audit_head    seq, hash   ← moved in the same transaction as each append

The console reads `tail(n)`: n+1 entries + the head, so verification cost stays O(n) however
long the history grows. `verify_all()` walks the whole chain (for audits, not page loads).
"""

from __future__ import annotations

import asyncio
from typing import Any

from jarvis.core.guardrails import ActionRisk
from jarvis.logging import get_logger
from jarvis.storage.docs import Docs, DocTx, Query
from jarvis.tools.audit import GENESIS, AuditEntry, AuditTail, make_entry, verify_window

log = get_logger(__name__)


class DocAuditLog:
    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self._d = docs
        self._col = f"{prefix}audit"
        self._head = f"{prefix}meta/audit_head"
        # In-process appends queue here instead of fighting over the head document's lock
        # (a burst of concurrent transactions can exhaust Firestore's retries). The
        # transaction still protects the chain across processes.
        self._append_lock = asyncio.Lock()

    def _path(self, seq: int) -> str:
        return f"{self._col}/{seq:012d}"

    async def append(
        self,
        *,
        agent: str,
        tool: str,
        risk: ActionRisk,
        outcome: str,
        args: dict[str, Any],
        detail: str = "",
    ) -> AuditEntry:
        async def link(tx: DocTx) -> AuditEntry:
            head = await tx.get(self._head)
            seq, prev = (int(head["seq"]), str(head["hash"])) if head else (0, GENESIS)
            e = make_entry(
                seq=seq + 1,
                prev_hash=prev,
                agent=agent,
                tool=tool,
                risk=risk,
                outcome=outcome,
                args=args,
                detail=detail,
            )
            tx.set(self._path(e.seq), {"seq": e.seq, "json": e.model_dump_json()})
            tx.set(self._head, {"seq": e.seq, "hash": e.hash})
            return e

        async with self._append_lock:
            return await self._d.transaction(link)

    async def _read_head(self) -> tuple[int, str] | None:
        head = await self._d.get(self._head)
        return (int(head["seq"]), str(head["hash"])) if head else None

    @staticmethod
    def _decode(rows: list[tuple[str, dict[str, Any]]]) -> list[AuditEntry] | None:
        try:
            return [AuditEntry.model_validate_json(str(d["json"])) for _, d in rows]
        except (KeyError, ValueError):
            return None  # an unreadable entry is a broken chain

    async def tail(self, limit: int) -> AuditTail:
        head = await self._read_head()
        if head is None or limit <= 0:
            return AuditTail(entries=[], verified=head is None or limit <= 0)
        rows = await self._d.query(
            Query(self._col, order_by="seq", descending=True, limit=limit + 1)
        )
        decoded = self._decode(rows)
        if decoded is None:
            log.error("audit chain has an unreadable entry")
            return AuditTail(entries=[], verified=False)
        newest_first = decoded
        has_pred = len(newest_first) > limit
        window = list(reversed(newest_first[:limit]))
        pred = newest_first[limit] if has_pred else None
        ok = verify_window(window, predecessor=pred, head=head)
        return AuditTail(entries=window, verified=ok)

    async def verify_all(self) -> bool:
        head = await self._read_head()
        rows = await self._d.query(Query(self._col, order_by="seq"))
        entries = self._decode(rows)
        if entries is None:
            return False
        return verify_window(entries, predecessor=None, head=head)
