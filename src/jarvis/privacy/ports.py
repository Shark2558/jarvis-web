# src/jarvis/privacy/ports.py
"""The privacy dashboard's ports (R2 D14; cross-cutting security).

Every feature that keeps something about the owner registers a `PrivacySource`; the dashboard
asks all of them at once (`PrivacyRegistry.describe_all`), each within its own time budget. A
source that fails, is slow or answers for another id still gets its row ("Couldn't check right
now", no count, nothing deletable): a category never disappears from the list (R1 D9 lesson).
Error text is logged as a class name only and never shown.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from jarvis.logging import get_logger

log = get_logger(__name__)

# none: explained, not deletable. simple: a setting or a link he can make again (confirm dialog).
# confirm: a confirm dialog that lists what goes. passkey: content that can't be brought back.
DeleteClass = Literal["none", "simple", "confirm", "passkey"]
SOURCE_BUDGET_S = 5.0
UNAVAILABLE_NOTE = "Couldn't check right now."


class CategoryView(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    section: str
    label: str
    what: str
    count: int | None
    unit: str
    retention: str
    where: str
    size_hint: str | None = None
    encrypted_by_jarvis: bool = False
    export: bool = False
    delete: DeleteClass = "none"
    recoverable: bool = False
    note: str = ""
    # a fingerprint of the data as it was shown; a delete quotes it, a changed one is refused
    rev: str = ""
    available: bool = True
    # how many of `count` a delete removes (None: all of them). The dialog shows this number.
    delete_count: int | None = None


@runtime_checkable
class PrivacySource(Protocol):
    id: str
    section: str
    label: str

    async def describe(self, uid: str) -> CategoryView: ...

    async def export(self, uid: str) -> dict[str, Any] | None: ...

    async def delete(self, uid: str) -> int: ...


def unavailable(source: PrivacySource) -> CategoryView:
    return CategoryView(
        id=source.id,
        section=source.section,
        label=source.label,
        what="",
        count=None,
        unit="",
        retention="",
        where="",
        note=UNAVAILABLE_NOTE,
        available=False,
    )


class PrivacyRegistry:
    def __init__(self, *, budget_s: float = SOURCE_BUDGET_S) -> None:
        self._sources: dict[str, PrivacySource] = {}
        self._budget_s = budget_s

    def register(self, source: PrivacySource) -> None:
        if source.id in self._sources:
            raise ValueError(f"privacy source {source.id!r} is already registered")
        self._sources[source.id] = source

    def get(self, category_id: str) -> PrivacySource | None:
        return self._sources.get(category_id)

    def ids(self) -> list[str]:
        return list(self._sources)

    async def _one(self, uid: str, source: PrivacySource) -> CategoryView:
        try:
            async with asyncio.timeout(self._budget_s):
                view = await source.describe(uid)
        except Exception as exc:  # noqa: BLE001 - one source never hides the others
            log.warning(
                "privacy source failed",
                extra={"source": source.id, "error": type(exc).__name__},
            )
            return unavailable(source)
        if not isinstance(view, CategoryView) or view.id != source.id:
            log.warning("privacy source answered for another category", extra={"source": source.id})
            return unavailable(source)
        return view

    async def describe_all(self, uid: str) -> list[CategoryView]:
        """One view per registered source, in registration order. Never raises."""
        return list(await asyncio.gather(*(self._one(uid, s) for s in self._sources.values())))


__all__ = [
    "SOURCE_BUDGET_S",
    "UNAVAILABLE_NOTE",
    "CategoryView",
    "DeleteClass",
    "PrivacyRegistry",
    "PrivacySource",
    "unavailable",
]
