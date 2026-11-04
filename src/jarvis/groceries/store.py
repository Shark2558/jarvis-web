# src/jarvis/groceries/store.py
"""Where the Groceries list lives (Layer 7): `{prefix}groceries/{uid}` = {list_id, title, found_at}.
Only a cache of the Google Tasks list id; the list itself is the owner's, in Google Tasks."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from jarvis.storage.docs import Docs

TITLE = "Groceries"


class GroceryStore:
    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self._d = docs
        self._col = f"{prefix}groceries"

    async def list_id(self, uid: str) -> str | None:
        doc: dict[str, Any] | None = await self._d.get(f"{self._col}/{uid}")
        value = doc.get("list_id") if doc else None
        return value if isinstance(value, str) and value else None

    async def remember(self, uid: str, list_id: str) -> None:
        from jarvis.storage.docs import Set

        data = {"list_id": list_id, "title": TITLE, "found_at": datetime.now(UTC).isoformat()}
        await self._d.write([Set(f"{self._col}/{uid}", data)])

    async def forget(self, uid: str) -> None:
        from jarvis.storage.docs import Delete

        await self._d.write([Delete(f"{self._col}/{uid}")])


__all__ = ["TITLE", "GroceryStore"]
