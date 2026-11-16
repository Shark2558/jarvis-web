# src/jarvis/wardrobe/styling/service.py
"""R13 Part C's one service (D12-D15): what the tools, the routes, the clock and the refresh share.

- `where(uid)`: now (`ctx.now()`, UTC, the only clock), his zone (`ctx.zone`), his local today;
  every "today" and "tomorrow" is a day in his zone (D15).
- `ask(...)`: an engine `Ask` for a day or a plan: the dress code, the weather it assumes
  (`outlook`), his "never" rules, exclusions and colours, what other plans hold (`reserve`), the
  declared shared base, his locks and the plan's own picks, the stale-sighting line (14 days).
- `look(...)`: a plan's look now (a worn plan shows what was worn), or a fresh suggestion.
- the plan actions behind `outfit_plan` (save, lock, change, reserve, transfer, release, share)
  and `outfit_prefs`'s dress code for a plan (STY-03). A plan's picks are saved from the
  engine's primary look; saving or previewing a plan changes no wear count (STY-17).
Off (no storage, no token key) or before A's store exists: every answer says so in words.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo

from jarvis.wardrobe.model import WardrobeView
from jarvis.wardrobe.ports import WardrobeContext
from jarvis.wardrobe.styling import reserve, texts
from jarvis.wardrobe.styling.engine import Ask, LookOut, Pick, Suggestion, suggest
from jarvis.wardrobe.styling.outlook import Outlook, Weather
from jarvis.wardrobe.styling.plans import (
    Plan,
    PlanPick,
    PlanRefused,
    StylingDoc,
    in_range,
    new_plan_id,
)
from jarvis.wardrobe.styling.rules import Rules
from jarvis.wardrobe.styling.sealed import SealedDoc, Told

OCCASION_WORDS = texts.OCCASION_WORDS
NO_EVENT = "no event planned"
Skip = dict[str, frozenset[str]]
_HHMM = 5


@dataclass(frozen=True)
class Here:
    now: datetime
    zone: tzinfo
    today: date


@dataclass(frozen=True)
class Answer:
    """One look for a day or a plan, and everything its words need."""

    day: date
    code: str
    phrase: str  # "your 10:00 event (a meeting)", "a festival", or "" (no event planned)
    suggestion: Suggestion
    weather: Weather
    plan: Plan | None = None


class Styling:
    def __init__(
        self, ctx: WardrobeContext, rules: Rules, plans: SealedDoc[StylingDoc], told: Told,
        outlook: Outlook,
    ) -> None:  # fmt: skip
        self.ctx, self.rules, self.plans, self.told, self.outlook = ctx, rules, plans, told, outlook

    # ---- where and what ---------------------------------------------------------------------
    def off(self) -> str | None:
        if self.ctx.docs is None:
            return texts.OFF_NO_STORE
        if self.ctx.keyring is None:
            return texts.OFF_NO_KEY
        return None

    async def where(self, uid: str) -> Here:
        now, zone = self.ctx.now(), await self.ctx.zone(uid)
        return Here(now, zone, now.astimezone(zone).date())

    async def view(self, uid: str) -> WardrobeView | None:
        store = self.ctx.store()
        return await store.view(uid) if store is not None else None

    @staticmethod
    def day_of(word: str | None, today: date) -> date | None:
        w = (word or "today").strip().lower()
        if w in ("today", "tonight"):
            return today
        if w == "tomorrow":
            return today + timedelta(days=1)
        try:
            day = date.fromisoformat(w)
        except ValueError:
            return None
        return day if in_range(day, today) else None

    @staticmethod
    def at(day: date, hhmm: str | None, zone: tzinfo) -> datetime | None:
        if not hhmm:
            return None
        h, _, m = hhmm.partition(":")
        if len(hhmm) != _HHMM or not (h.isdigit() and m.isdigit()):
            raise PlanRefused("A time is HH:MM, like 10:00.")
        if int(h) > 23 or int(m) > 59:
            raise PlanRefused("A time is HH:MM, like 10:00.")
        return datetime.combine(day, time(int(h), int(m)), tzinfo=zone)

    def phrase(self, plan: Plan | None, occasion: str | None, zone: tzinfo) -> str:
        occ = OCCASION_WORDS.get(occasion or "")
        base = texts.event_words(plan.starts, zone) if plan is not None else ""
        if base and occ:
            return f"{base} ({occ})"
        return base or occ or ""

    @staticmethod
    def planned(doc: StylingDoc, day: date, here: Here, occasion: str | None) -> tuple[Plan, ...]:
        """The plans "what should I wear" answers with: the day's plans, of the occasion he
        names (code review H3); for today, only those not worn and not over (L3)."""
        found = [p for p in doc.on(day) if occasion is None or p.occasion == occasion]
        if day == here.today:
            found = [p for p in found if not p.worn and reserve.window(p, here.zone)[1] > here.now]
        return tuple(found)

    # ---- asks and looks ---------------------------------------------------------------------
    async def ask(
        self, uid: str, here: Here, doc: StylingDoc, *, day: date, code: str,
        occasion: str | None, plan: Plan | None = None, skip: Skip | None = None,
        out: bool | None = None,
    ) -> tuple[Ask, Weather]:  # fmt: skip
        span = reserve.window(plan, here.zone) if plan is not None and plan.starts else None
        weather = await self.outlook.weather(uid, day, span, here.zone)
        probe = plan or Plan(id="op_00000000", day=day, code=code)
        held = reserve.reserved_for(doc, probe, here.zone)
        earlier = frozenset(
            i for i, o in held.items() if plan is not None and reserve.can_share_from(o, plan)
        )
        prefs = doc.prefs
        ask = Ask(
            day=day, code=code, occasion=occasion, rain=weather.rain, hot=weather.hot,
            cold=weather.cold, outdoor=plan.outdoor if plan is not None else out,
            locked={p.slot: p.pieces for p in (plan.picks if plan else ()) if p.locked},
            keep={p.slot: p.pieces for p in (plan.picks if plan else ()) if not p.locked},
            skip=skip or {},
            shared={i: plan.shared_from for i in plan.shared} if plan and plan.shared_from else {},
            reserved={i: reserve.held_words(o, here.zone) for i, o in held.items()},
            earlier=earlier,
            never=tuple((n.feature, n.value) for n in prefs.never),
            excluded=frozenset(e.piece for e in prefs.excluded if e.occasion in (None, occasion)),
            likes=frozenset(prefs.likes), avoids=frozenset(prefs.avoids),
            stale_before=here.now - timedelta(days=self.ctx.s.wardrobe_stale_days),
            for_words=self.phrase(plan, occasion, here.zone), zone=here.zone,
        )  # fmt: skip
        return ask, weather

    async def answer(
        self, uid: str, here: Here, doc: StylingDoc, view: WardrobeView, plan: Plan
    ) -> Answer:
        """A plan's look now (a worn one: what was worn)."""
        ask, weather = await self.ask(
            uid, here, doc, day=plan.day, code=plan.code, occasion=plan.occasion, plan=plan
        )
        if plan.worn:
            picks = tuple(_pick(p) for p in plan.picks)
            worn = LookOut(
                picks, (f"Worn for {self.phrase(plan, plan.occasion, here.zone) or 'this plan'}.",)
            )
            return Answer(plan.day, plan.code, ask.for_words, Suggestion(worn), weather, plan)
        got = suggest(view, ask, self.rules)
        primary = self._shared_words(doc, plan, got.primary, view, here.zone)
        return Answer(
            plan.day, plan.code, ask.for_words, Suggestion(primary, got.alternatives), weather, plan
        )

    async def fresh(
        self, uid: str, here: Here, doc: StylingDoc, view: WardrobeView, *, day: date,
        occasion: str | None, code: str | None, out: bool | None = None,
    ) -> Answer:  # fmt: skip
        chosen = code or self.rules.code_of(occasion, event=False)
        ask, weather = await self.ask(
            uid, here, doc, day=day, code=chosen, occasion=occasion, out=out
        )
        return Answer(day, chosen, ask.for_words, suggest(view, ask, self.rules), weather)

    def _shared_words(
        self, doc: StylingDoc, plan: Plan, look: LookOut, view: WardrobeView, zone: tzinfo
    ) -> LookOut:
        source = doc.plan(plan.shared_from) if plan.shared_from else None
        if source is None or not plan.shared:
            return look
        units = [p for p in look.picks if set(p.pieces) & set(plan.shared)]
        reused = ", ".join(
            f"{texts.unit_words([view.pieces[i] for i in p.pieces])} ({texts.ids_words(p.pieces)})"
            for p in units
        )
        change = [self.rules.slot_words_of(p.slot) for p in look.picks if p not in units]
        lines = (
            f"Reused from {reserve.held_words(source, zone)}: {reused}.",
            f"Change for this one: {texts.ids_words(change)}.",
        )
        return LookOut(look.picks, (*look.reasons, *lines), look.compromises, look.gaps)

    # ---- plan actions -----------------------------------------------------------------------
    def new_plan(
        self, here: Here, *, day: date, occasion: str | None, code: str | None,
        starts: datetime | None, ends: datetime | None,
    ) -> Plan:  # fmt: skip
        if code is not None and code not in self.rules.codes:
            raise PlanRefused("That isn't one of the dress codes.")
        if (starts is None) != (ends is None) or (starts and ends and ends <= starts):
            raise PlanRefused("A plan's start and end go together, the end after the start.")
        chosen = code or self.rules.code_of(occasion, event=starts is not None)
        return Plan(
            id=new_plan_id(), day=day, starts=starts, ends=ends, code=chosen,
            tentative=code is None, occasion=occasion, created_at=here.now, updated_at=here.now,
        )  # fmt: skip

    async def repick(
        self, uid: str, here: Here, doc: StylingDoc, view: WardrobeView, plan: Plan,
        skip: dict[str, frozenset[str]] | None = None,
    ) -> Plan:  # fmt: skip
        """The plan with its unlocked picks from the engine's primary look now."""
        ask, _ = await self.ask(
            uid,
            here,
            doc,
            day=plan.day,
            code=plan.code,
            occasion=plan.occasion,
            plan=plan,
            skip=skip,
        )
        look = suggest(view, ask, self.rules).primary
        picks = tuple(PlanPick(slot=p.slot, pieces=p.pieces, locked=p.locked) for p in look.picks)
        return plan.model_copy(update={"picks": picks, "needs": (), "updated_at": here.now})

    async def change(self, uid: str, fn: Callable[[StylingDoc], StylingDoc]) -> StylingDoc:
        here = await self.where(uid)
        return await self.plans.change(uid, lambda d: fn(d).pruned(here.today))


def _pick(p: PlanPick) -> Pick:
    return Pick(p.slot, p.pieces, p.locked)


__all__ = ["NO_EVENT", "OCCASION_WORDS", "Answer", "Here", "Styling"]
