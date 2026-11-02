# src/jarvis/storage/approvals.py
"""ApprovalStore on the Docs port: pending R3 actions survive scale-to-zero.

Single use is enforced by a transaction (read → check → delete), so a double click, a retry,
or two instances can never execute the same approved action twice.
"""

from __future__ import annotations

from datetime import UTC, datetime

from jarvis.core.guardrails import ActionMatcher, ApprovalStore, PendingAction
from jarvis.logging import get_logger
from jarvis.storage.docs import Delete, Docs, DocTx, Query, Set
from jarvis.storage.sessions import safe_id

log = get_logger(__name__)
LIST_LIMIT = 100


def _decode(data: dict[str, object] | None) -> PendingAction | None:
    if data is None:
        return None
    try:
        return PendingAction.model_validate_json(str(data["json"]))
    except (KeyError, ValueError):
        log.error("unreadable approval document")
        return None


class DocApprovalStore(ApprovalStore):
    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self._d = docs
        self._col = f"{prefix}approvals"

    def _path(self, approval_id: str) -> str:
        return f"{self._col}/{approval_id}"

    async def put(self, action: PendingAction) -> None:
        if not safe_id(action.id):
            raise ValueError("invalid approval id")
        await self._d.write(
            [
                Set(
                    self._path(action.id),
                    {
                        "scope": action.scope,
                        "created_at": action.created_at,
                        "expires_at": action.expires_at,
                        "json": action.model_dump_json(),
                    },
                )
            ]
        )

    async def get(self, approval_id: str) -> PendingAction | None:
        if not safe_id(approval_id):
            return None
        return _decode(await self._d.get(self._path(approval_id)))

    async def consume(self, approval_id: str, matches: ActionMatcher) -> PendingAction | None:
        if not safe_id(approval_id):
            return None
        path = self._path(approval_id)

        async def take(tx: DocTx) -> PendingAction | None:
            a = _decode(await tx.get(path))
            if a is None or a.expired or not matches(a):
                return None
            tx.delete(path)
            return a

        return await self._d.transaction(take)

    async def cancel(self, approval_id: str) -> PendingAction | None:
        if not safe_id(approval_id):
            return None
        path = self._path(approval_id)

        async def take(tx: DocTx) -> PendingAction | None:
            a = _decode(await tx.get(path))
            if a is not None:
                tx.delete(path)
            return a

        return await self._d.transaction(take)

    async def pending_in(self, scope: str | None) -> list[PendingAction]:
        """One conversation's waiting cards only (an equality query: Firestore's automatic
        single-field index), so a proposal never reads every card (integration review L4).
        Expired ones are skipped here and tidied by `list_pending`."""
        if scope is None:
            return await super().pending_in(scope)
        rows = await self._d.query(Query(self._col, where=("scope", scope), limit=LIST_LIMIT))
        now = datetime.now(UTC)
        live = [a for _, d in rows if (a := _decode(d)) is not None and a.expires_at >= now]
        return sorted(live, key=lambda a: a.created_at)

    async def list_pending(self) -> list[PendingAction]:
        rows = await self._d.query(Query(self._col, order_by="created_at", limit=LIST_LIMIT))
        now = datetime.now(UTC)
        live: list[PendingAction] = []
        expired: list[str] = []
        for aid, data in rows:
            a = _decode(data)
            if a is None or a.expires_at < now:
                expired.append(aid)
            else:
                live.append(a)
        if expired:  # tidy lazily; a handful of deletes a day at most
            await self._d.write([Delete(self._path(aid)) for aid in expired])
        return live
