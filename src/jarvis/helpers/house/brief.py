# src/jarvis/helpers/house/brief.py
"""Part B in the brief's "Helpers" section and in "what is pending" (docs/plans/r11-free-helpers.md
D9, D12, D13; I0 seam 8). Fixed templates only, at most 3 lines a contributor:

- `ChoresBrief` ("house"): "Chores today: Dishes 21:00, Laundry 18:00." and the upkeep due soon,
  today or overdue ("Home upkeep: AC service due today."). Rota names are left out.
- `OutsideBrief` ("outside"): the SACHET warnings still in force for his district (`feed.live`:
  expired ones and ones a day old with no expiry are left out), the gravest first ("Urgent:
  Landslide warning for Ernakulam until 18:00 (SACHET)."), then today's weather line with
  Open-Meteo's attribution. An outage (SACHET's feed or its CAP messages; Open-Meteo) always
  keeps its line, so the warnings take what room is left (code review L7).
- `HousePending` ("house"): overdue and due upkeep, and today's chores not done yet.
"""

from __future__ import annotations

from datetime import date, datetime, tzinfo

from jarvis.helpers.house import chores, feed, upkeep, words
from jarvis.helpers.house.cap import RANK
from jarvis.helpers.house.models import Outside, zone_of
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
    ranked = sorted(feed.live(o.sachet.warnings, now), key=lambda w: -RANK.get(w.kind, 0))
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
        outages = _outages(o, tz)
        room = MAX_BRIEF_LINES - len(outages)
        warnings = _warning_lines(o, self._svc.ctx.now(), tz)[:room]
        s = o.weather.summary
        weather = []
        if s is not None and s.day == day.isoformat() and o.weather.fail_since is None:
            weather = [words.brief_weather(s.t_max, s.rain_from)][: room - len(warnings)]
        return [*warnings, *weather, *outages]


def _hhmm(iso: str, tz: tzinfo) -> str:
    return datetime.fromisoformat(iso).astimezone(tz).strftime("%H:%M")


def _outages(o: Outside, tz: tzinfo) -> list[str]:
    out = []
    sachet = [x for x in (o.sachet.fail_since, o.sachet.cap_fail_since) if x is not None]
    if sachet:
        out.append(words.brief_outage("SACHET", _hhmm(min(sachet, key=datetime.fromisoformat), tz)))
    if o.weather.fail_since is not None:
        out.append(words.brief_weather_outage(_hhmm(o.weather.fail_since, tz)))
    return out


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
                due = datetime.combine(upkeep.due_date(x), upkeep.AT, tzinfo=zone_of(tz))
                items.append(PendingItem("house", f"Upkeep: {x.label}", urgency, due, ref=x.id))
        for c in await self._svc.store.chores(uid):
            if chores.occurs_on(c, today) and c.last_done != today.isoformat():
                due = chores.due_at(c, today, tz)
                items.append(PendingItem("house", f"Chore: {c.label}", "today", due, ref=c.id))
        return sorted(items, key=lambda i: (_ORDER[i.urgency], i.due or now))


__all__ = ["ChoresBrief", "HousePending", "OutsideBrief"]
