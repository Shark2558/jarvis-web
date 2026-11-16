# src/jarvis/wardrobe/styling/data.py
"""R13 Part C's data for D's Privacy rows (D20, the "Outfit plans" row): a count, a
plain export (no calendar id, no title: there is none to give) and delete-everything (his plans,
rules and choices, the last calendar read, the weather summary and C's once-only claims).
"""

from __future__ import annotations

from typing import Any

from jarvis.wardrobe.kept import WardrobeUnavailable
from jarvis.wardrobe.ports import PrivacyRow
from jarvis.wardrobe.styling.calendar import Calendar
from jarvis.wardrobe.styling.plans import StylingDoc
from jarvis.wardrobe.styling.sealed import Off, Unreadable
from jarvis.wardrobe.styling.service import Styling


class OutfitsData:
    name = "outfits"
    row: PrivacyRow = "plans"

    def __init__(self, styling: Styling, calendar: Calendar) -> None:
        self._s, self._cal = styling, calendar

    async def kept(self, uid: str) -> int:
        """Documents on disk for him, found with no key (plans, calendar, weather, claims)."""
        sealed = (self._s.plans, self._cal.sealed, self._s.outlook.sealed)
        return sum([await d.present(uid) for d in sealed]) + await self._s.told.count(uid)

    async def _doc(self, uid: str) -> Any:
        """The plans document; "Couldn't check right now" (not an empty one) when data is kept
        that can't be opened (no key, a changed key): Privacy then asks `kept` and can delete."""
        try:
            return await self._s.plans.read(uid)
        except (Off, Unreadable):
            if await self.kept(uid):
                raise WardrobeUnavailable(self.name) from None
            return StylingDoc()

    async def count(self, uid: str) -> int:
        return len((await self._doc(uid)).plans)

    async def export(self, uid: str) -> dict[str, Any]:
        doc = await self._doc(uid)
        plans = [
            {"day": p.day.isoformat(), "starts": p.starts.isoformat() if p.starts else None,
             "dress_code": p.code, "occasion": p.occasion, "pieces": list(p.pieces()),
             "manual": p.manual, "cancelled": p.cancelled, "worn": p.worn}
            for p in doc.plans
        ]  # fmt: skip
        rules = doc.prefs.model_dump(mode="json")
        return {"plans": plans, "rules": rules, "calendar_chosen": doc.choice.calendar is not None}

    async def delete(self, uid: str) -> int:
        gone = 0
        for sealed in (self._s.plans, self._cal.sealed, self._s.outlook.sealed):
            gone += await sealed.delete(uid)
        return gone + await self._s.told.delete(uid)


__all__ = ["OutfitsData"]
