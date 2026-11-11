# src/jarvis/helpers/house/service.py
"""Part B's one service, shared by its routes (`api/helpers_house.py`) and its tools (`tools.py`),
so the tab and the chat change the same data the same way (docs/plans/r11-free-helpers.md D10-D14).

Every change is a transaction on the store. Labels are his own words (`models.clean_label`); his
place is kept only sealed (`OutsideStore`, no keyring: `OutsideOff`). `view(uid)` is the Home
tab's whole state as plain JSON: the outside words of a SACHET warning appear only under
`outside_text`, which the tab shows as SACHET's own words (never as JARVIS's).
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from datetime import date, time
from typing import Any

from jarvis.helpers.house import chores, upkeep, words
from jarvis.helpers.house.models import (
    STATES,
    WEEKDAYS,
    Chore,
    Freq,
    Outside,
    Place,
    SachetState,
    Thresholds,
    Unit,
    Upkeep,
    WeatherState,
)
from jarvis.helpers.house.store import OFF_WORDS, HouseStore, OutsideOff, OutsideStore
from jarvis.helpers.ports import HelperContext
from jarvis.helpers.sources import OPEN_METEO_ATTRIBUTION, SACHET_ATTRIBUTION
from jarvis.notify.quiet import local

FREQ_WORDS = {"daily": "every day", "weekly": "on {days}", "every": "every {n} days"}


def _new_id() -> str:
    return secrets.token_hex(4)


def _find(items: Sequence[Any], ref: str, what: str) -> Any:
    key = " ".join(ref.split()).lower()
    hit = [x for x in items if x.id == key] or [x for x in items if x.label.lower() == key]
    if not hit:
        raise ValueError(f"No {what} called '{ref[:40]}', Sir.")
    return hit[0]


def weekday_numbers(days: Sequence[object]) -> tuple[int, ...]:
    out = []
    for d in days:
        word = str(d).strip().lower()[:3]
        if word not in WEEKDAYS:
            raise ValueError("Days are Monday to Sunday (mon, tue, ...).")
        out.append(WEEKDAYS.index(word))
    return tuple(sorted(set(out)))


def how_often(c: Chore) -> str:
    days = ", ".join(WEEKDAYS[d].title() for d in c.days)
    return FREQ_WORDS[c.freq].format(days=days, n=c.every)


class HouseService:
    def __init__(self, ctx: HelperContext, store: HouseStore, outside: OutsideStore) -> None:
        self.ctx = ctx
        self.store = store
        self.outside = outside

    def today(self) -> date:
        return local(self.ctx.now(), self.ctx.tz).date()

    def now_time(self) -> time:
        return local(self.ctx.now(), self.ctx.tz).time()

    # ---- chores ---------------------------------------------------------------------------------
    async def add_chore(
        self,
        uid: str,
        *,
        label: str,
        freq: Freq,
        at: str = "09:00",
        days: Sequence[object] = (),
        every: int | None = None,
        members: Sequence[str] = (),
    ) -> Chore:
        new = chores.new_chore(
            cid=_new_id(),
            label=label,
            freq=freq,
            today=self.today(),
            at=at,
            days=weekday_numbers(days) if freq == "weekly" else (),
            every=every,
            members=members,
            now_time=self.now_time(),
        )
        await self.store.change_chores(uid, lambda cs: _no_twin(cs, new))
        return new

    async def chore_done(self, uid: str, ref: str) -> Chore:
        today, found = self.today(), []

        def done(cs: tuple[Chore, ...]) -> tuple[Chore, ...]:
            hit = _find(cs, ref, "chore")
            found.append(chores.mark_done(hit, today))
            return tuple(found[-1] if c.id == hit.id else c for c in cs)

        await self.store.change_chores(uid, done)
        return found[-1]

    async def remove_chore(self, uid: str, cid: str) -> None:
        await self.store.change_chores(uid, lambda cs: _without(cs, cid, "chore"))

    # ---- upkeep ---------------------------------------------------------------------------------
    async def add_upkeep(
        self,
        uid: str,
        *,
        label: str,
        every: int,
        unit: Unit = "days",
        last_done: date | None = None,
        lead: int = 7,
    ) -> Upkeep:
        new = upkeep.new_upkeep(
            cid=_new_id(),
            label=label,
            every=every,
            unit=unit,
            last_done=last_done or self.today(),
            lead=lead,
        )
        await self.store.change_upkeep(uid, lambda xs: _no_twin(xs, new))
        return new

    async def upkeep_done(self, uid: str, ref: str, day: date | None = None) -> Upkeep:
        when, found = day or self.today(), []

        def done(xs: tuple[Upkeep, ...]) -> tuple[Upkeep, ...]:
            hit = _find(xs, ref, "upkeep item")
            found.append(upkeep.mark_upkeep_done(hit, when))
            return tuple(found[-1] if x.id == hit.id else x for x in xs)

        await self.store.change_upkeep(uid, done)
        return found[-1]

    async def remove_upkeep(self, uid: str, cid: str) -> None:
        await self.store.change_upkeep(uid, lambda xs: _without(xs, cid, "upkeep item"))

    # ---- his place, thresholds, breach watch ----------------------------------------------------
    async def set_place(
        self, uid: str, place: Place, thresholds: Thresholds | None = None
    ) -> Outside:
        def put(o: Outside) -> Outside:
            moved = o.place != place
            update: dict[str, Any] = {"place": place, "thresholds": thresholds or o.thresholds}
            if moved:  # a new place: its feeds start over
                update |= {"weather": WeatherState(), "sachet": SachetState()}
            return o.model_copy(update=update)

        return await self.outside.change(uid, put)

    async def clear_place(self, uid: str) -> Outside:
        return await self.outside.change(
            uid,
            lambda o: o.model_copy(
                update={"place": None, "weather": WeatherState(), "sachet": SachetState()}
            ),
        )

    async def set_breach(self, uid: str, on: bool) -> Outside:
        return await self.outside.change(uid, lambda o: o.model_copy(update={"breach_on": on}))

    async def read_outside(self, uid: str) -> Outside | None:
        try:
            return await self.outside.read(uid)
        except OutsideOff:
            return None

    # ---- the tab's view -------------------------------------------------------------------------
    async def view(self, uid: str) -> dict[str, Any]:
        today = self.today()
        cs, xs = await self.store.chores(uid), await self.store.upkeep(uid)
        have = {x.label.lower() for x in xs}
        return {
            "chores": [chore_view(c, today) for c in cs],
            "upkeep": [upkeep_view(x, today) for x in xs],
            "starters": [s for s in upkeep.STARTERS if str(s["label"]).lower() not in have],
            "adults_only": words.ADULTS_ONLY,
            "outside": self._outside_view(await self.read_outside(uid)),
        }

    def _outside_view(self, o: Outside | None) -> dict[str, Any]:
        s = self.ctx.settings
        base: dict[str, Any] = {
            "available": o is not None,
            "off": None if o is not None else OFF_WORDS,
            "states": list(STATES),
            "official_first": words.OFFICIAL_FIRST,
            "attribution": {"weather": OPEN_METEO_ATTRIBUTION, "sachet": SACHET_ATTRIBUTION},
            "weather_enabled": s.weather_enabled,
            "disaster_enabled": s.disaster_alerts_enabled,
            "breach_how": words.BREACH_HOW,
            "breach_link": words.HIBP_NOTIFY,
            "google_linked": self.ctx.google is not None,
        }
        if o is None:
            return base
        return {**base, **outside_state(o)}


def _without(items: tuple[Any, ...], ref: str, what: str) -> tuple[Any, ...]:
    hit = _find(items, ref, what)
    return tuple(x for x in items if x.id != hit.id)


def _no_twin(items: tuple[Any, ...], new: Any) -> tuple[Any, ...]:
    if any(x.label.lower() == new.label.lower() for x in items):
        raise ValueError(f"'{new.label}' is already on the list, Sir.")
    return (*items, new)


def chore_view(c: Chore, today: date) -> dict[str, Any]:
    nxt = chores.next_on_or_after(c, today)
    on = nxt or today
    return {
        "id": c.id,
        "label": c.label,
        "freq": c.freq,
        "how_often": how_often(c),
        "days": [WEEKDAYS[d] for d in c.days],
        "every": c.every,
        "at": c.at,
        "members": list(c.members),
        "whose": chores.whose(c, on),
        "next": nxt.isoformat() if nxt else None,
        "today": chores.occurs_on(c, today),
        "done_today": c.last_done == today.isoformat(),
    }


def upkeep_view(x: Upkeep, today: date) -> dict[str, Any]:
    return {
        "id": x.id,
        "label": x.label,
        "every": x.every,
        "unit": x.unit,
        "last_done": x.last_done,
        "lead": x.lead,
        "due": upkeep.due_date(x).isoformat(),
        "state": upkeep.state(x, today),
    }


def outside_state(o: Outside) -> dict[str, Any]:
    w, sa = o.weather, o.sachet
    return {
        "place": o.place.model_dump(mode="json") if o.place else None,
        "point_known": bool(o.place and o.place.point()),
        "feed": o.place.feed() if o.place else None,
        "thresholds": o.thresholds.model_dump(mode="json"),
        "weather": {
            "summary": w.summary.model_dump(mode="json") if w.summary else None,
            "checked_at": w.checked_at,
            "ok_at": w.ok_at,
            "fail_since": w.fail_since,
        },
        "sachet": {
            "checked_at": sa.checked_at,
            "ok_at": sa.ok_at,
            "fail_since": sa.fail_since,
            "cap_fail_since": sa.cap_fail_since,
            "warnings": [
                {
                    "kind": x.kind,
                    "event": x.event,
                    "until": x.until,
                    "outside_text": {"headline": x.headline, "instruction": x.instruction},
                }
                for x in sa.warnings
            ],
        },
        "breach": {"on": o.breach_on, **o.breach.model_dump(mode="json")},
    }


__all__ = [
    "HouseService",
    "chore_view",
    "how_often",
    "outside_state",
    "upkeep_view",
    "weekday_numbers",
]
