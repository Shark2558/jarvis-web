# src/jarvis/tools/audit.py
"""Append-only, hash-chained action audit (Layer 7).

`AuditTrail` is the contract; `AuditLog` is the in-process implementation (dev/tests) and
`jarvis.storage.audit.DocAuditLog` the persistent one. Both share the hashing and the window
verification below, so a chain written by one verifies with the other.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel

from jarvis.core.guardrails import ActionRisk
from jarvis.logging import get_trace_id

GENESIS = "genesis"
MAX_DETAIL_CHARS = 500


class AuditEntry(BaseModel):
    seq: int
    at: datetime
    trace_id: str
    agent: str
    tool: str
    risk: ActionRisk
    outcome: str
    args_hash: str
    detail: str = ""
    prev_hash: str
    hash: str = ""


@dataclass(frozen=True)
class AuditTail:
    """The newest entries (oldest → newest) and whether they verify."""

    entries: list[AuditEntry] = field(default_factory=list)
    verified: bool = True


def _digest(entry: dict[str, Any], prev: str) -> str:
    body = json.dumps(entry, sort_keys=True, default=str)
    return hashlib.sha256(f"{prev}|{body}".encode()).hexdigest()


def args_hash(args: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()[:16]


def entry_hash(e: AuditEntry) -> str:
    return _digest(e.model_dump(mode="json", exclude={"hash"}), e.prev_hash)


def make_entry(
    *,
    seq: int,
    prev_hash: str,
    agent: str,
    tool: str,
    risk: ActionRisk,
    outcome: str,
    args: dict[str, Any],
    detail: str = "",
) -> AuditEntry:
    e = AuditEntry(
        seq=seq,
        at=datetime.now(UTC),
        trace_id=get_trace_id(),
        agent=agent,
        tool=tool,
        risk=risk,
        outcome=outcome,
        args_hash=args_hash(args),
        detail=detail[:MAX_DETAIL_CHARS],
        prev_hash=prev_hash,
    )
    return e.model_copy(update={"hash": entry_hash(e)})


def verify_window(
    window: Sequence[AuditEntry],
    *,
    predecessor: AuditEntry | None,
    head: tuple[int, str] | None,
) -> bool:
    """True iff every entry recomputes, seqs are contiguous, each links to the one before,
    the first links to `predecessor` (or genesis at seq 1), the predecessor itself recomputes,
    and the last entry is the chain head. Cost is O(window), not O(history)."""
    if not window:
        return head is None
    if predecessor is not None:
        if entry_hash(predecessor) != predecessor.hash or predecessor.seq != window[0].seq - 1:
            return False
        prev = predecessor.hash
    elif window[0].seq == 1:
        prev = GENESIS
    else:
        return False  # the entry before the window is missing
    for i, e in enumerate(window):
        if e.seq != window[0].seq + i or e.prev_hash != prev or entry_hash(e) != e.hash:
            return False
        prev = e.hash
    last = window[-1]
    return head is None or head == (last.seq, last.hash)


class AuditTrail(Protocol):
    async def append(
        self,
        *,
        agent: str,
        tool: str,
        risk: ActionRisk,
        outcome: str,
        args: dict[str, Any],
        detail: str = "",
    ) -> AuditEntry: ...

    async def tail(self, limit: int) -> AuditTail: ...

    async def verify_all(self) -> bool: ...


class AuditLog:
    """In-process AuditTrail. State dies with the process."""

    GENESIS = GENESIS

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []
        self._lock = asyncio.Lock()

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
        async with self._lock:
            last = self._entries[-1] if self._entries else None
            e = make_entry(
                seq=(last.seq + 1) if last else 1,
                prev_hash=last.hash if last else GENESIS,
                agent=agent,
                tool=tool,
                risk=risk,
                outcome=outcome,
                args=args,
                detail=detail,
            )
            self._entries.append(e)
            return e

    async def tail(self, limit: int) -> AuditTail:
        n = max(0, limit)
        window = self._entries[-n:] if n else []
        start = len(self._entries) - len(window)
        pred = self._entries[start - 1] if start > 0 else None
        return AuditTail(
            entries=list(window), verified=verify_window(window, predecessor=pred, head=None)
        )

    async def verify_all(self) -> bool:
        return verify_window(self._entries, predecessor=None, head=None)
