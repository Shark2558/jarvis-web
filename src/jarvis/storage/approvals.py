# src/jarvis/storage/approvals.py
"""ApprovalStore on the Docs port: pending R3 actions survive scale-to-zero.

Single use is enforced by a transaction (read → check → delete), so a double click, a retry,
or two instances can never execute the same approved action twice.

R18 review: a feature may seal what a card holds at rest (`use_seal`, an `ArgumentSeal`): the
action is sealed on the way in and opened on the way out, so the gate and everything after it
see the whole arguments. A card that doesn't open is unreadable (never a guess), like a bad
document. The calls' seal (`jarvis.calls.pending`) keeps a waiting call's number sealed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from jarvis.core.guardrails import ActionMatcher, ApprovalStore, PendingAction
from jarvis.logging import get_logger
from jarvis.storage.docs import Delete, Docs, DocTx, Query, Set
from jarvis.storage.sessions import safe_id

log = get_logger(__name__)
LIST_LIMIT = 100


class ArgumentSeal(Protocol):
    """Seals a card's arguments for storage and opens them again (raises when they don't)."""

    def seal(self, action: PendingAction) -> PendingAction: ...

    def open(self, action: PendingAction) -> PendingAction: ...


class DocApprovalStore(ApprovalStore):
    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self._d = docs
        self._col = f"{prefix}approvals"
        self.seal: ArgumentSeal | None = None

    def use_seal(self, seal: ArgumentSeal) -> None:
        self.seal = seal

    def _decode(self, data: dict[str, object] | None) -> PendingAction | None:
        if data is None:
            return None
        try:
            action = PendingAction.model_validate_json(str(data["json"]))
            return self.seal.open(action) if self.seal is not None else action
        except Exception as exc:  # noqa: BLE001 - unreadable or not opening: never a guess
            log.error("unreadable approval document", extra={"error": type(exc).__name__})
            return None

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
                        "json": self._sealed(action).model_dump_json(),
                    },
                )
            ]
        )

    def _sealed(self, action: PendingAction) -> PendingAction:
        return self.seal.seal(action) if self.seal is not None else action

    async def get(self, approval_id: str) -> PendingAction | None:
        if not safe_id(approval_id):
            return None
        return self._decode(await self._d.get(self._path(approval_id)))

    async def consume(self, approval_id: str, matches: ActionMatcher) -> PendingAction | None:
        if not safe_id(approval_id):
            return None
        path = self._path(approval_id)

        async def take(tx: DocTx) -> PendingAction | None:
            a = self._decode(await tx.get(path))
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
            a = self._decode(await tx.get(path))
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
        live = [a for _, d in rows if (a := self._decode(d)) is not None and a.expires_at >= now]
        return sorted(live, key=lambda a: a.created_at)

    async def list_pending(self) -> list[PendingAction]:
        rows = await self._d.query(Query(self._col, order_by="created_at", limit=LIST_LIMIT))
        now = datetime.now(UTC)
        live: list[PendingAction] = []
        expired: list[str] = []
        for aid, data in rows:
            a = self._decode(data)
            if a is None or a.expires_at < now:
                expired.append(aid)
            else:
                live.append(a)
        if expired:  # tidy lazily; a handful of deletes a day at most
            await self._d.write([Delete(self._path(aid)) for aid in expired])
        return live
