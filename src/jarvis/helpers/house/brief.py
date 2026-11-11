# src/jarvis/helpers/house/brief.py
"""Part B in the brief's "Helpers" section and in "what is pending" (docs/plans/r11-free-helpers.md
D9, D12, D13; I0 seam 8). Fixed templates only, at most 3 lines a contributor:

- `ChoresBrief` ("house"): "Chores today: Dishes 21:00, Laundry 18:00." and the upkeep due soon,
  today or overdue ("Home upkeep: AC service due today."). Rota names are left out.
- `OutsideBrief` ("outside"): the SACHET warnings still active for his district, the gravest
  first ("Urgent: Landslide warning for Ernakulam until 18:00 (SACHET)."), then today's weather
  line with Open-Meteo's attribution, or that SACHET can't be reached and since when.
- `HousePending` ("house"): overdue and due upkeep, and today's chores not done yet.
"""

from __future__ import annotations

from datetime import date, datetime, tzinfo
from zoneinfo import ZoneInfo

from jarvis.helpers.house import chores, upkeep, words
from jarvis.helpers.house.models import Outside
from jarvis.helpers.house.sachet import RANK
from jarvis.helpers.house.service import HouseService
from jarvis.helpers.ports import MAX_BRIEF_LINES, PendingItem, Urgency
from jarvis.notify.quiet import local

MAX_CHORES_LISTED = 4
_ORDER: dict[str, int] = {"overdue": 0, "today": 1, "soon": 2, "later": 3}
_URGENCY: dict[str, Urgency] = {"overdue": "overdue", "due": "today", "soon": "soon"}


def _dm(d: date) -> str:
    return f"{d.day} {d.strftime('%b')}"


class ChoresBrief:
    name = "house"

    def __init__(self, svc: HouseService) -> None:
        self._svc = svc

    async def lines(self, uid: str, tz: tzinfo, day: date) -> list[str]:
        out: list[str] = []
        due = sorted(
            (c for c in await self._svc.store.chores(uid) if chores.occurs_on(c, day)),
            key=lambda c: c.at,
        )
        todo = [f"{c.label} {c.at}" for c in due if c.last_done != day.isoformat()]
        if todo:
            out.append(f"Chores today: {', '.join(todo[:MAX_CHORES_LISTED])}.")
        for x in sorted(await self._svc.store.upkeep(uid), key=upkeep.due_date):
            state, when = upkeep.state(x, day), upkeep.due_date(x)
            if state == "overdue":
                out.append(f"Home upkeep: {x.label} overdue since {_dm(when)}.")
            elif state == "due":
                out.append(f"Home upkeep: {x.label} due today.")
            elif state == "soon":
                out.append(f"Home upkeep: {x.label} due on {_dm(when)}.")
        return out[:MAX_BRIEF_LINES]


def _warning_lines(o: Outside, now: datetime, tz: tzinfo) -> list[str]:
    if o.place is None:
        return []
    ranked = sorted(o.sachet.warnings, key=lambda w: -RANK.get(w.kind, 0))
    here = now.astimezone(tz)
    out = []
    for w in ranked:
        ends = words.until(
            datetime.fromisoformat(w.until).astimezone(tz) if w.until else None, here
        )
        out.append(words.brief_warning(w.kind, w.event, o.place.district, ends))
    return out


class OutsideBrief:
    name = "outside"

    def __init__(self, svc: HouseService) -> None:
        self._svc = svc

    async def lines(self, uid: str, tz: tzinfo, day: date) -> list[str]:
        o = await self._svc.read_outside(uid)
        if o is None or o.place is None:
            return []
        now = self._svc.ctx.now()
        last: list[str] = []
        s = o.weather.summary
        if s is not None and s.day == day.isoformat():
            last.append(words.brief_weather(s.t_max, s.rain_from))
        if o.sachet.fail_since is not None:
            since = datetime.fromisoformat(o.sachet.fail_since).astimezone(tz)
            last.append(words.brief_outage("SACHET", since.strftime("%H:%M")))
        warnings = _warning_lines(o, now, tz)[: MAX_BRIEF_LINES - min(1, len(last))]
        return [*warnings, *last][:MAX_BRIEF_LINES]


class HousePending:
    name = "house"

    def __init__(self, svc: HouseService) -> None:
        self._svc = svc

    async def pending(self, uid: str, now: datetime) -> list[PendingItem]:
        tz = self._svc.ctx.tz
        today = local(now, tz).date()
        items: list[PendingItem] = []
        for x in await self._svc.store.upkeep(uid):
            urgency = _URGENCY.get(upkeep.state(x, today))
            if urgency is not None:
                due = datetime.combine(upkeep.due_date(x), upkeep.AT, tzinfo=ZoneInfo(tz))
                items.append(PendingItem("house", f"Upkeep: {x.label}", urgency, due, ref=x.id))
        for c in await self._svc.store.chores(uid):
            if chores.occurs_on(c, today) and c.last_done != today.isoformat():
                due = chores.due_at(c, today, tz)
                items.append(PendingItem("house", f"Chore: {c.label}", "today", due, ref=c.id))
        return sorted(items, key=lambda i: (_ORDER[i.urgency], i.due or now))


__all__ = ["ChoresBrief", "HousePending", "OutsideBrief"]
