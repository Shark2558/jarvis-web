# src/jarvis/wardrobe/styling/data.py
"""R13 Part C's data for D's Privacy rows (D20, "Laundry, outfits and wear history"): a count, a
plain export (no calendar id, no title: there is none to give) and delete-everything (his plans,
rules and choices, the last calendar read, the weather summary and C's once-only claims).
"""

from __future__ import annotations

from typing import Any

from jarvis.wardrobe.styling.calendar import Calendar
from jarvis.wardrobe.styling.sealed import Off, Unreadable
from jarvis.wardrobe.styling.service import Styling


class OutfitsData:
    name = "outfits"
    row = "history"

    def __init__(self, styling: Styling, calendar: Calendar) -> None:
        self._s, self._cal = styling, calendar

    async def count(self, uid: str) -> int:
        try:
            return len((await self._s.plans.read(uid)).plans)
        except (Off, Unreadable):
            return 0

    async def export(self, uid: str) -> dict[str, Any]:
        try:
            doc = await self._s.plans.read(uid)
        except (Off, Unreadable):
            return {"plans": [], "rules": {}, "calendar_chosen": False}
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
