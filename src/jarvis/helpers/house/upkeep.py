# src/jarvis/helpers/house/upkeep.py
"""Item 3, the home maintenance schedule (docs/plans/r11-free-helpers.md D11, D3).

An item is due `every` days or months after its last-done day (a month-end date clamps: 30 Nov
plus 3 months is 28 Feb). `UpkeepJob` (`maint_due`, the 5-minute clock) sends `maintenance_due`
at 09:00 his time on the lead day ("Home upkeep: AC service is due on 17 Nov.") and on the due day
("Home upkeep due today: AC service."), each once (a claim per item, due day and which one;
released when no channel took it). `STARTERS` is offered in the tab, never added by itself.
"""

from __future__ import annotations

import calendar
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from typing import Literal

from jarvis.helpers.house import words
from jarvis.helpers.house.guard import Counts, allowed, tally
from jarvis.helpers.house.models import Unit, Upkeep, zone_of
from jarvis.helpers.house.store import HouseStore
from jarvis.helpers.ports import HelperContext
from jarvis.logging import get_logger
from jarvis.notify.quiet import local

log = get_logger(__name__)

JOB = "maint_due"
AT = time(9, 0)
State = Literal["ok", "soon", "due", "overdue"]
STARTERS: tuple[dict[str, object], ...] = (
    {"label": "Water-purifier filter", "every": 90, "unit": "days"},
    {"label": "AC service", "every": 180, "unit": "days"},
    {"label": "Fire-extinguisher check", "every": 365, "unit": "days"},
    {"label": "Gas pipe check", "every": 365, "unit": "days"},
)


def add_months(d: date, n: int) -> date:
    month = d.month - 1 + n
    year, month = d.year + month // 12, month % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def due_date(item: Upkeep) -> date:
    done = date.fromisoformat(item.last_done)
    if item.unit == "months":
        return add_months(done, item.every)
    return done + timedelta(days=item.every)


def lead_date(item: Upkeep) -> date:
    return due_date(item) - timedelta(days=item.lead)


def state(item: Upkeep, today: date) -> State:
    due = due_date(item)
    if today > due:
        return "overdue"
    if today == due:
        return "due"
    return "soon" if today >= lead_date(item) else "ok"


def new_upkeep(
    *, cid: str, label: str, every: int, unit: Unit = "days", last_done: date, lead: int = 7
) -> Upkeep:
    return Upkeep(
        id=cid, label=label, every=every, unit=unit, last_done=last_done.isoformat(), lead=lead
    )


def mark_upkeep_done(item: Upkeep, day: date) -> Upkeep:
    return item.model_copy(update={"last_done": day.isoformat()})


def _at(day: date, tz: str) -> datetime:
    return datetime.combine(day, AT, tzinfo=zone_of(tz))


class UpkeepJob:
    name = JOB
    budget_s = 3.0

    def __init__(self, ctx: HelperContext, store: HouseStore) -> None:
        self._ctx = ctx
        self._store = store

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        """`owners` is ignored: the helpers serve the configured owners (`ctx.owners`)."""
        n = Counts()
        for uid in self._ctx.owners:
            try:
                if not await allowed(self._ctx, uid, "maint_list"):
                    n.add("skipped")
                    continue
                await self._owner(uid, n)
            except Exception as exc:  # noqa: BLE001 - one owner never blocks another
                log.warning("upkeep job failed for an owner", extra={"error": type(exc).__name__})
                n.add("failed")
        return n.done("sent", "retry", "skipped", "failed")

    async def _owner(self, uid: str, n: Counts) -> None:
        now = self._ctx.now()
        today = local(now, self._ctx.tz).date()
        due_time = _at(today, self._ctx.tz)
        if now < due_time:
            return
        for item in await self._store.upkeep(uid):
            due = due_date(item)
            if today == due:
                await self._one(uid, item, "due", words.upkeep_due(item.label), due_time, n)
            elif item.lead and today == lead_date(item):
                text = words.upkeep_soon(item.label, due)
                await self._one(uid, item, "lead", text, due_time, n)

    async def _one(
        self, uid: str, item: Upkeep, which: str, text: str, due: datetime, n: Counts
    ) -> None:
        ident = f"{item.id}|{due_date(item).isoformat()}|{which}"

        async def send() -> bool:
            return tally(await self._ctx.sender.send(uid, "maintenance_due", text, due=due), n)

        await self._store.once(uid, "upkeep", ident, self._ctx.now(), send)


__all__ = [
    "JOB",
    "STARTERS",
    "UpkeepJob",
    "add_months",
    "due_date",
    "lead_date",
    "mark_upkeep_done",
    "new_upkeep",
    "state",
]
