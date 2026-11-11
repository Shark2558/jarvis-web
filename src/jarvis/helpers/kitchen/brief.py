# src/jarvis/helpers/kitchen/brief.py
"""The kitchen's line in the brief's Helpers section (docs/plans/r11-free-helpers.md D15): on the
1st of the month, last month's grocery total from his receipts, when receipts are on. A fixed
template (the month, the amount, the number of orders); never a merchant's words, never AI input.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, tzinfo

from jarvis.helpers.kitchen.spend import SpendService


class KitchenBrief:
    name = "kitchen"

    def __init__(self, spend: SpendService) -> None:
        self._spend = spend

    async def lines(self, uid: str, tz: tzinfo, day: date) -> Sequence[str]:
        if day.day != 1 or not self._spend.store.sealed:
            return []
        prev = date(day.year - 1, 12, 1) if day.month == 1 else date(day.year, day.month - 1, 1)
        got = await self._spend.month(uid, prev.strftime("%Y-%m"))
        if "total" not in got:
            return []
        n = int(got["orders"])
        return [
            f"Groceries in {got['label']}: about {got['total']} from {n} "
            f"order{'s' if n != 1 else ''} (your e-mailed receipts)."
        ]


__all__ = ["KitchenBrief"]
