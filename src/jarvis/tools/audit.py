# src/jarvis/tools/audit.py
"""Append-only, hash-chained action audit (Layer 7). Postgres-backed in a later slice."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from jarvis.core.guardrails import ActionRisk
from jarvis.logging import get_trace_id


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


def _digest(entry: dict[str, Any], prev: str) -> str:
    body = json.dumps(entry, sort_keys=True, default=str)
    return hashlib.sha256(f"{prev}|{body}".encode()).hexdigest()


def args_hash(args: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()[:16]


class AuditLog:
    GENESIS = "genesis"

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    def append(
        self,
        *,
        agent: str,
        tool: str,
        risk: ActionRisk,
        outcome: str,
        args: dict[str, Any],
        detail: str = "",
    ) -> AuditEntry:
        prev = self._entries[-1].hash if self._entries else self.GENESIS
        e = AuditEntry(
            seq=len(self._entries) + 1,
            at=datetime.now(UTC),
            trace_id=get_trace_id(),
            agent=agent,
            tool=tool,
            risk=risk,
            outcome=outcome,
            args_hash=args_hash(args),
            detail=detail[:500],
            prev_hash=prev,
        )
        e = e.model_copy(
            update={"hash": _digest(e.model_dump(mode="json", exclude={"hash"}), prev)}
        )
        self._entries.append(e)
        return e

    def entries(self) -> list[AuditEntry]:
        return list(self._entries)

    def verify(self) -> bool:
        prev = self.GENESIS
        for e in self._entries:
            if (
                e.prev_hash != prev
                or _digest(e.model_dump(mode="json", exclude={"hash"}), prev) != e.hash
            ):
                return False
            prev = e.hash
        return True
