# src/jarvis/family/store.py
"""`{prefix}family_calendars/{uid}` = {members: [...]} on the Docs port (Layer 7). Changes are
read-modify-write in one transaction, so two adds cannot both take the last free place."""

from __future__ import annotations

from typing import Any

from jarvis.family.models import MAX_MEMBERS, Member
from jarvis.logging import get_logger
from jarvis.storage.docs import Docs, DocTx

log = get_logger(__name__)


class FamilyFull(Exception):
    pass


class FamilyDuplicate(Exception):
    pass


def _decode(doc: dict[str, Any] | None) -> list[Member]:
    out: list[Member] = []
    for raw in (doc or {}).get("members") or []:
        try:
            out.append(Member.model_validate(raw))
        except ValueError:
            log.warning("a family member record was unreadable and is ignored")
    return out


class FamilyStore:
    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self._d = docs
        self._col = f"{prefix}family_calendars"

    def _path(self, uid: str) -> str:
        return f"{self._col}/{uid}"

    async def members(self, uid: str) -> list[Member]:
        return _decode(await self._d.get(self._path(uid)))

    async def add(self, uid: str, member: Member) -> None:
        path = self._path(uid)

        async def fn(tx: DocTx) -> None:
            cur = _decode(await tx.get(path))
            if len(cur) >= MAX_MEMBERS:
                raise FamilyFull()
            if any(
                m.calendar_id == member.calendar_id or m.name.casefold() == member.name.casefold()
                for m in cur
            ):
                raise FamilyDuplicate()
            tx.set(path, {"members": [m.model_dump(mode="json") for m in [*cur, member]]})

        await self._d.transaction(fn)

    async def remove(self, uid: str, member_id: str) -> bool:
        path = self._path(uid)

        async def fn(tx: DocTx) -> bool:
            cur = _decode(await tx.get(path))
            keep = [m for m in cur if m.id != member_id]
            if len(keep) == len(cur):
                return False
            tx.set(path, {"members": [m.model_dump(mode="json") for m in keep]})
            return True

        return await self._d.transaction(fn)


__all__ = ["FamilyDuplicate", "FamilyFull", "FamilyStore"]
