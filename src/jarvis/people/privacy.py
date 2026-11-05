# src/jarvis/people/privacy.py
"""People research in the privacy dashboard (R4 I2 F3): the owner's LAST research (a public figure's
or due-diligence dossier, kept an hour) can be exported and deleted. A refused target is never
stored, so there is nothing of that kind to list. Deleting is simple: the entry lives one hour.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from jarvis.people.cache import TTL_S, DossierCache
from jarvis.privacy.ports import CategoryView

CATEGORY_ID = "people_research"
SECTION = "People research"
HOUR_S = 3600


class PeoplePrivacy:
    id = CATEGORY_ID
    section = SECTION
    label = "Your last people lookup"

    def __init__(self, cache: DossierCache) -> None:
        self._cache = cache

    async def describe(self, uid: str) -> CategoryView:
        entry = await self._cache.get(uid)
        stored = entry is not None and entry.dossier is not None
        return CategoryView(
            id=self.id,
            section=self.section,
            label=self.label,
            what="The links and short summary of the last public figure or business you "
            "looked up. A refused request is never saved.",
            count=1 if stored else 0,
            unit="lookup",
            retention=f"{int(TTL_S // HOUR_S)} hour, then it is deleted",
            where="Firestore (Mumbai), deleted automatically after an hour",
            export=True,
            delete="simple" if stored else "none",
            recoverable=False,
            rev="1" if stored else "0",
        )

    async def export(self, uid: str) -> dict[str, Any] | None:
        entry = await self._cache.get(uid)
        if entry is None or entry.dossier is None:
            return None
        return {"name": entry.name, "context": entry.context, "dossier": asdict(entry.dossier)}

    async def delete(self, uid: str) -> int:
        entry = await self._cache.get(uid)
        await self._cache.clear(uid)
        return 1 if entry is not None and entry.dossier is not None else 0


__all__ = ["CATEGORY_ID", "SECTION", "PeoplePrivacy"]
