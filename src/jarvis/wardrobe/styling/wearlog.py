# src/jarvis/wardrobe/styling/wearlog.py
"""R13 `wear_log` (STY-15, STY-17; plan review H1): "I'm wearing ..." and "I wore ... / done for
today", through A's ledger (`wear.commit`), never by hand.

The pieces of a wear: by id; a plan's look NOW (a substitute he took is what he wears, H1); his
words (`query`, D10's one exception); or, for "done" alone, everything In use. A name that fits
several pieces asks "Which one: ...?" and writes nothing. A card's words come from `card` through
`redact` ("a private basic").
"""

from __future__ import annotations

from typing import Any

from jarvis.tools.base import Preview
from jarvis.wardrobe.model import WardrobeView
from jarvis.wardrobe.redact import card_words
from jarvis.wardrobe.styling import texts, wear
from jarvis.wardrobe.styling.answers import plural, ready, refused, uid, via
from jarvis.wardrobe.styling.plans import StylingDoc
from jarvis.wardrobe.styling.service import Here, Styling


class WearLog:
    def __init__(self, s: Styling) -> None:
        self.s = s

    async def run(self, args: dict[str, Any]) -> dict[str, Any]:
        got = await ready(self.s)
        if isinstance(got, dict):
            return got
        who, here, doc, view = got
        pieces, why = await self._pieces(who, here, doc, view, args)
        store = self.s.ctx.store()
        if why or store is None:
            return refused(why or texts.NOT_READY_YET)
        if args.get("action") == "start":
            return await self._start(who, here, doc, view, pieces, args)
        in_use = [i for i in pieces if view.pieces[i].state == "in_use"]
        if not in_use:
            return refused("Nothing named is in use.")
        events = wear.done_events(view, in_use, self.s.rules, here.now, via=via())
        await wear.commit(store, who, events)
        words = f"Done for today: {plural(len(in_use), 'piece')}, one wear each."
        return {"pieces": in_use, "message": words}

    async def _start(
        self, who: str, here: Here, doc: StylingDoc, view: WardrobeView, pieces: list[str],
        args: dict[str, Any],
    ) -> dict[str, Any]:  # fmt: skip
        out = [view.pieces[i] for i in pieces if view.pieces[i].state not in ("ready", "in_use")]
        if out:
            return refused(f"{texts.states_line(out)}: not wearable now.")
        store = self.s.ctx.store()
        assert store is not None
        plan = args.get("plan") if doc.plan(str(args.get("plan"))) else None
        await wear.commit(store, who, wear.start_events(view, pieces, plan, here.now, via=via()))
        words = texts.ids_words([texts.unit_words([view.pieces[i]]) for i in pieces[:3]])
        more = " and more" if len(pieces) > 3 else ""
        return {"pieces": pieces, "message": f"Noted: you're wearing {words}{more}."}

    async def _pieces(
        self, who: str, here: Here | None, doc: StylingDoc | None, view: WardrobeView,
        args: dict[str, Any],
    ) -> tuple[list[str], str]:  # fmt: skip
        """By id; a plan's look NOW (a substitute he took, H1); his words; or all in use."""
        named = [str(i) for i in args.get("pieces") or []]
        if named:
            missing = [i for i in named if i not in view.pieces]
            if missing:
                return [], f"{texts.ids_words(missing)} isn't in your wardrobe."
            return named, ""
        plan = doc.plan(str(args.get("plan"))) if doc is not None and args.get("plan") else None
        if plan is not None and doc is not None and here is not None:
            ans = await self.s.answer(who, here, doc, view, plan)
            return list(ans.suggestion.primary.ids()), ""
        if args.get("query"):
            return wear.resolve(view, str(args["query"]))
        if args.get("action") == "done":
            active = sorted(view.active(), key=lambda x: x.id)
            return [p.id for p in active if p.state == "in_use"], ""
        return [], "Say which pieces, or the plan you are wearing."

    async def card(self, args: dict[str, Any]) -> Preview:
        """A wear card's words: fixed words through `redact` ("a private basic")."""
        who = uid()
        view = await self.s.view(who)
        if view is None:
            return Preview("Log a wear.")
        on = self.s.off() is None
        doc = await self.s.plans.read(who) if on else None
        here = await self.s.where(who) if on else None
        pieces, _ = await self._pieces(who, here, doc, view, args)
        words = [card_words(view.pieces[i]) for i in pieces if i in view.pieces]
        return Preview(f"Log a wear: {texts.ids_words(words)}." if words else "Log a wear.")


__all__ = ["WearLog"]
