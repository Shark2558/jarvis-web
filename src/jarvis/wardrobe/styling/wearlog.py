# src/jarvis/wardrobe/styling/wearlog.py
"""R13 `wear_log` (STY-15, STY-17; plan review H1; code review 1 H1, M3, M6; security review 1
L8): "I'm wearing ..." and "I wore ... / done for today", through A's ledger (`wear.commit`),
never by hand.

The pieces of a wear: by id; a plan's look NOW (a substitute he took is what he wears, H1); his
words (`query`, D10's one exception: "the meeting outfit" is today's plan, code review H1); or,
for "done" alone, everything In use. "Done" for a plan he is wearing closes what is In use for it
(the substitute too, M3).
- A start that names no plan is linked to today's plan holding a named piece (`wear.plan_for`),
  so wearing a planned shirt by its name is a wear FOR that plan: nothing is sent (H1).
- "I wore ... today / yesterday" (`day`: today, yesterday or a date at most 30 days back, his
  local day) for a piece that is Ready is one wear told after the fact: its start and end in ONE
  commit at 12:00 his time that day (now, if that is ahead), linked to that day's plan (M6, D4.1).
- The ledger's verdict is said: its refusal in its own plain words, "Already noted" when it took
  nothing new (security L8).
A name that fits several pieces asks "Which one: ...?" and writes nothing. A card's words come
from `card` through `redact` ("a private basic").
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from jarvis.tools.base import Preview
from jarvis.wardrobe.model import WardrobeView
from jarvis.wardrobe.ports import Refused
from jarvis.wardrobe.redact import card_words
from jarvis.wardrobe.styling import texts, wear
from jarvis.wardrobe.styling.answers import plural, ready, refused, uid, via
from jarvis.wardrobe.styling.plans import Plan, StylingDoc
from jarvis.wardrobe.styling.sealed import Unreadable
from jarvis.wardrobe.styling.service import Here, Styling

NO_OUTFIT = "You have no outfit planned for today: say which pieces you are wearing."
BAD_DAY = "A wear's day is today, yesterday or a date up to 30 days back."
START_NOW = "A wear starts now: for an earlier day, say you wore it."
NOTHING = "Nothing named is in use."
BACK_DAYS = 30
NOON = time(12, 0)
Found = tuple[list[str], str, Plan | None]


def wear_day(word: Any, today: date) -> date | None:
    """His local day of a wear: today, yesterday or a date up to 30 days back, never ahead."""
    w = str(word or "today").strip().lower()
    if w in ("today", "yesterday"):
        return today - timedelta(days=0 if w == "today" else 1)
    try:
        day = date.fromisoformat(w)
    except ValueError:
        return None
    return day if timedelta(0) <= today - day <= timedelta(days=BACK_DAYS) else None


def _when(day: date, today: date) -> str:
    return {0: "today", 1: "yesterday"}.get((today - day).days, f"on {texts.date_words(day)}")


def _words(view: WardrobeView, pieces: list[str]) -> str:
    more = " and more" if len(pieces) > 3 else ""
    return texts.ids_words([texts.unit_words([view.pieces[i]]) for i in pieces[:3]]) + more


class WearLog:
    def __init__(self, s: Styling) -> None:
        self.s = s

    async def run(self, args: dict[str, Any]) -> dict[str, Any]:
        got = await ready(self.s)
        if isinstance(got, dict):
            return got
        who, here, doc, view = got
        day, start = wear_day(args.get("day"), here.today), args.get("action") == "start"
        if day is None or (start and day != here.today):
            return refused(BAD_DAY if day is None else START_NOW)
        pieces, why, chosen = await self._pieces(who, here, doc, view, args)
        if why or self.s.ctx.store() is None:
            return refused(why or texts.NOT_READY_YET)
        try:
            if start:
                return await self._start(who, here, doc, view, pieces, chosen)
            return await self._done(who, here, doc, view, pieces, chosen, day)
        except Refused as exc:  # the ledger's own plain words; nothing was written
            return refused(str(exc))

    async def _start(
        self, who: str, here: Here, doc: StylingDoc, view: WardrobeView, pieces: list[str],
        chosen: Plan | None,
    ) -> dict[str, Any]:  # fmt: skip
        out = [view.pieces[i] for i in pieces if view.pieces[i].state not in ("ready", "in_use")]
        if out:
            return refused(f"{texts.states_line(out)}: not wearable now.")
        store = self.s.ctx.store()
        assert store is not None
        plan = chosen.id if chosen is not None else None
        plan = plan or wear.plan_for(doc, pieces, here.today, here.zone, after=here.now)
        events = wear.start_events(view, pieces, plan, here.now, via=via())
        got = await wear.commit(store, who, events)
        lead = "Noted" if wear.counted(got, wear_done=False) else "Already noted"
        return {"pieces": pieces, "message": f"{lead}: you're wearing {_words(view, pieces)}."}

    async def _done(
        self, who: str, here: Here, doc: StylingDoc, view: WardrobeView, pieces: list[str],
        chosen: Plan | None, day: date,
    ) -> dict[str, Any]:  # fmt: skip
        in_use = [i for i in pieces if view.pieces[i].state == "in_use"]
        fresh = [i for i in pieces if view.pieces[i].state == "ready"]
        if not in_use and not fresh:
            out = [view.pieces[i] for i in pieces]
            return refused(f"{texts.states_line(out)}: not counted." if out else NOTHING)
        store = self.s.ctx.store()
        assert store is not None
        r, how = self.s.rules, via()
        events = wear.done_events(view, in_use, r, here.now, via=how)
        if fresh:
            at = min(datetime.combine(day, NOON, tzinfo=here.zone), here.now)
            plan = chosen.id if chosen is not None and chosen.day == day else None
            plan = plan or wear.plan_for(doc, fresh, day, here.zone, after=None)
            events = (*events, *wear.worn_events(view, fresh, r, at, plan, via=how))
        got = await wear.commit(store, who, events)
        if not wear.counted(got, wear_done=True):
            return {"pieces": in_use + fresh, "message": "Already noted."}
        lines = (
            [f"Done for today: {plural(len(in_use), 'piece')}, one wear each."] if in_use else []
        )
        if fresh:
            each = " each" if len(fresh) > 1 else ""
            when = _when(day, here.today)
            lines.append(f"Noted: {_words(view, fresh)}, worn {when}: one wear{each}.")
        return {"pieces": in_use + fresh, "message": " ".join(lines)}

    async def _pieces(
        self, who: str, here: Here | None, doc: StylingDoc | None, view: WardrobeView,
        args: dict[str, Any],
    ) -> Found:  # fmt: skip
        """By id; a plan's look NOW (a substitute he took, H1); his words; or all in use."""
        named = [str(i) for i in args.get("pieces") or []]
        if named:
            missing = [i for i in named if i not in view.pieces]
            if missing:
                return [], f"{texts.ids_words(missing)} isn't in your wardrobe.", None
            return named, "", None
        query = str(args.get("query") or "")
        plan = doc.plan(str(args.get("plan"))) if doc is not None and args.get("plan") else None
        if plan is None and doc is not None and here is not None and wear.means_outfit(query):
            occ = self.s.rules.occasion_of(query)
            done = args.get("action") == "done"
            plan = wear.outfit_of(doc, here.today, here.zone, occ, now=here.now, done=done)
            if plan is None:
                return [], NO_OUTFIT, None
        if plan is not None and plan.worn:  # what is In use for it, a substitute too (M3)
            active = sorted(view.active(), key=lambda x: x.id)
            return [p.id for p in active if p.state == "in_use" and p.wear == plan.id], "", plan
        if plan is not None and doc is not None and here is not None:
            ans = await self.s.answer(who, here, doc, view, plan)
            return list(ans.suggestion.primary.ids()), "", plan
        if query:
            return (*wear.resolve(view, query), None)
        if args.get("action") == "done":
            active = sorted(view.active(), key=lambda x: x.id)
            return [p.id for p in active if p.state == "in_use"], "", None
        return [], "Say which pieces, or the plan you are wearing.", None

    async def card(self, args: dict[str, Any]) -> Preview:
        """A wear card's words: fixed words through `redact` ("a private basic")."""
        who = uid()
        view = await self.s.view(who)
        if view is None:
            return Preview("Log a wear.")
        on = self.s.off() is None
        try:
            doc = await self.s.plans.read(who) if on else None
        except Unreadable:
            doc = None
        here = await self.s.where(who) if doc is not None else None
        pieces, _, _ = await self._pieces(who, here, doc, view, args)
        words = [card_words(view.pieces[i]) for i in pieces if i in view.pieces]
        return Preview(f"Log a wear: {texts.ids_words(words)}." if words else "Log a wear.")


__all__ = ["BAD_DAY", "NO_OUTFIT", "START_NOW", "WearLog", "wear_day"]
