# tests/privacy_fakes.py - a scriptable PrivacySource for the R2 D workstream tests.
from __future__ import annotations

from typing import Any

from jarvis.privacy import CategoryView, DeleteClass
from jarvis.privacy.export import fingerprint


class FakeSource:
    """Holds `items` per owner; describe/export/delete work on that list."""

    def __init__(
        self,
        id: str,
        *,
        delete: DeleteClass = "simple",
        exportable: bool = True,
        section: str = "Test",
        items: dict[str, list[str]] | None = None,
        secret: str | None = None,
    ) -> None:
        self.id, self.section, self.label = id, section, id.title()
        self.delete_class, self.exportable = delete, exportable
        self.items = items if items is not None else {}
        self.secret = secret
        self.fail_describe = False
        self.fail_delete = False
        self.noop_delete = False  # reports 0 and leaves the rows (a swallowed failure)
        self.deleted_calls: list[str] = []

    def _mine(self, uid: str) -> list[str]:
        return list(self.items.get(uid, []))

    async def describe(self, uid: str) -> CategoryView:
        if self.fail_describe:
            raise RuntimeError("boom with secret text")
        mine = self._mine(uid)
        return CategoryView(
            id=self.id,
            section=self.section,
            label=self.label,
            what="things",
            count=len(mine),
            unit="items",
            retention="until deleted",
            where="Firestore",
            export=self.exportable,
            delete=self.delete_class,
            rev=fingerprint(self.id, mine),
            delete_count=len(mine),
        )

    async def export(self, uid: str) -> dict[str, Any] | None:
        if not self.exportable:
            return None
        data: dict[str, Any] = {"items": self._mine(uid)}
        if self.secret is not None:
            data["access_token"] = self.secret
            data["nested"] = {"api_key": self.secret, "ok": True}
        return data

    async def delete(self, uid: str) -> int:
        self.deleted_calls.append(uid)
        if self.fail_delete:
            raise RuntimeError("delete failed")
        if self.noop_delete:
            return 0
        n = len(self._mine(uid))
        self.items[uid] = []
        return n
