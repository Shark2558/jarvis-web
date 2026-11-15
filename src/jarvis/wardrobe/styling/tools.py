# src/jarvis/wardrobe/styling/tools.py
"""R13 Part C's five tools (docs/plans/r13-wardrobe.md "Tools", D10, D18); every call passes the
gateway (policy, cards, the audit); the panel calls the same tools through A's
`POST /v1/wardrobe/tools/{tool}` (D1).

| tool | risk | what |
|---|---|---|
| `outfit_suggest` | R1, No-AI | a day's look ("today", "tomorrow" in his zone, or a date; an occasion in his words; a dress code): the day's plans when it has some, else a fresh suggestion |
| `outfit_plans` | R1 | the plans ahead (or one day's) with their looks now |
| `outfit_plan` | R2 | save, lock, change, reserve, transfer, release, share (`actions`) |
| `outfit_prefs` | R2 | never / allow, exclude / include, like / avoid, a plan's dress code (`prefs`) |
| `wear_log` | R2, `spoken_ok`, No-AI | start / done a wear (`wear`); pieces by id, a plan, or his words (`query`, D10's one exception) |

Results: piece ids and fixed words only (`views`), at most 20 pieces; the reads vouch for their
result (every string is a fixed-list word or JARVIS's own sentence, never his label or a title,
D18). A card's words come from `preview` through `redact` (fixed words, "a private basic").
Untrusted by default (`trusted_output` False); Activity shows fixed words.
"""

from __future__ import annotations

from typing import Any

from jarvis.core.guardrails import ActionRisk
from jarvis.tools.base import Preview, Tool
from jarvis.tools.context import current_tool_context, require_tool_context
from jarvis.tools.provenance import vouch
from jarvis.wardrobe.ports import MAX_RESULT_PIECES
from jarvis.wardrobe.redact import card_words
from jarvis.wardrobe.styling import actions, prefs, texts, views, wear
from jarvis.wardrobe.styling.plans import PlanRefused
from jarvis.wardrobe.styling.service import Styling

AGENT = "outfits"
R1, R2 = ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE
_S = {"type": "string"}
_IDS = {"type": "array", "items": {"type": "string"}, "maxItems": 20}


def _schema(props: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(required)}


SUGGEST = _schema({
    "day": {**_S, "description": "today, tomorrow (his time zone) or YYYY-MM-DD"},
    "occasion": {**_S, "maxLength": 60, "description": "his words: the meeting, Diwali, Holi"},
    "code": {**_S, "description": "a dress code: business_formal, business_casual, smart_casual, casual, festive, mess_tolerant, sport"},  # noqa: E501
})  # fmt: skip
PLANS = _schema({"day": _S, "days": {"type": "integer", "minimum": 1, "maximum": 14}})
PLAN = _schema({
    "action": {"type": "string", "enum": list(actions.ACTIONS)}, "plan": _S, "day": _S,
    "occasion": {**_S, "maxLength": 60}, "code": _S, "start": _S, "end": _S, "slot": _S,
    "piece": _S, "pieces": _IDS, "from_plan": _S,
}, ("action",))  # fmt: skip
PREFS = _schema({
    "action": {"type": "string", "enum": list(prefs.ACTIONS)}, "feature": _S, "value": _S,
    "piece": _S, "occasion": {**_S, "maxLength": 60}, "plan": _S, "code": _S,
}, ("action",))  # fmt: skip
WEAR = _schema({
    "action": {"type": "string", "enum": ["start", "done"]}, "pieces": _IDS, "plan": _S,
    "query": {**_S, "maxLength": 80, "description": "his words, for the spoken one-step path"},
}, ("action",))  # fmt: skip


def _uid() -> str:
    return require_tool_context().user_id


def _refused(message: str) -> dict[str, Any]:
    return {"refused": True, "message": message}


def _via() -> str:
    ctx = current_tool_context()
    return "voice" if ctx is not None and ctx.spoken else "chat"


class StylingTools:
    def __init__(self, s: Styling) -> None:
        self.s = s

    async def _ready(self) -> tuple[Any, ...] | dict[str, Any]:
        s = self.s
        if (off := s.off()) is not None:
            return _refused(off)
        uid = _uid()
        view = await s.view(uid)
        if view is None:
            return _refused(texts.NOT_READY_YET)
        return uid, await s.where(uid), await s.plans.read(uid), view

    async def suggest(self, args: dict[str, Any]) -> Any:
        got = await self._ready()
        if isinstance(got, dict):
            return got
        uid, here, doc, view = got
        s = self.s
        day = s.day_of(args.get("day"), here.today)
        if day is None:
            return _refused("Ask for today, tomorrow or a date up to 30 days ahead.")
        occ = s.rules.occasion_of(str(args["occasion"])) if args.get("occasion") else None
        code = args.get("code") if args.get("code") in s.rules.codes else None
        planned = doc.on(day) if occ is None and code is None else ()
        answers = [await s.answer(uid, here, doc, view, p) for p in planned] or [
            await s.fresh(uid, here, doc, view, day=day, occasion=occ, code=code)
        ]
        looks, budget = [], MAX_RESULT_PIECES
        for ans in answers:
            got_look, used = views.answer_dict(view, ans, s.rules, here, budget=budget)
            looks.append(got_look)
            budget -= used
        first = answers[0]
        out = {"day": day.isoformat(), "message": views.message(view, first, s.rules, here),
               "looks": looks, "alternatives": views.alternatives(view, first, budget)}  # fmt: skip
        return vouch(out, True)

    async def plans(self, args: dict[str, Any]) -> Any:
        got = await self._ready()
        if isinstance(got, dict):
            return got
        uid, here, doc, view = got
        day = self.s.day_of(args["day"], here.today) if args.get("day") else None
        days = int(args.get("days") or 7)
        found = [
            p
            for p in doc.plans
            if (p.day == day if day else here.today <= (p.day) and (p.day - here.today).days < days)
        ]  # noqa: E501
        out, budget = [], MAX_RESULT_PIECES
        for p in found:
            ans = await self.s.answer(uid, here, doc, view, p)
            entry, used = views.answer_dict(view, ans, self.s.rules, here, budget=budget)
            out.append(
                {
                    "id": p.id,
                    **entry,
                    "look": {k: entry[k] for k in ("pieces", "reasons", "compromises", "gaps")},
                }
            )  # noqa: E501
            budget -= used
        return vouch(
            {"plans": out, "message": f"{len(out)} plan{'s' if len(out) != 1 else ''}."}, True
        )  # noqa: E501

    async def plan(self, args: dict[str, Any]) -> dict[str, Any]:
        got = await self._ready()
        if isinstance(got, dict):
            return got
        uid = got[0]
        try:
            plan, words = await actions.run(self.s, uid, args)
        except PlanRefused as exc:
            return _refused(str(exc))
        if plan is None:
            return {"message": words}
        return {"message": words, "plan": await self._plan_dict(uid, plan.id)}

    async def _plan_dict(self, uid: str, pid: str) -> dict[str, Any]:
        here, doc, view = (
            await self.s.where(uid),
            await self.s.plans.read(uid),
            await self.s.view(uid),
        )  # noqa: E501
        plan = doc.plan(pid)
        assert plan is not None and view is not None
        ans = await self.s.answer(uid, here, doc, view, plan)
        entry, _ = views.answer_dict(view, ans, self.s.rules, here)
        return {
            "id": plan.id,
            **entry,
            "look": {k: entry[k] for k in ("pieces", "reasons", "compromises", "gaps")},
        }  # noqa: E501

    async def prefs(self, args: dict[str, Any]) -> dict[str, Any]:
        got = await self._ready()
        if isinstance(got, dict):
            return got
        uid, here, doc, view = got
        s = self.s
        try:
            if args.get("action") == "code":
                fixed = prefs.set_code(doc, s.rules, args.get("plan"), args.get("code"))
                plan = fixed.plan(str(args["plan"]))
                assert plan is not None
                plan = await s.repick(uid, here, fixed, view, plan)
                await s.change(uid, lambda d: d.put(plan))
                return {
                    "message": f"Dress code set: {s.rules.code_words(plan.code)}.",
                    "plan": await self._plan_dict(uid, plan.id),
                }  # noqa: E501
            new, words = prefs.apply(doc.prefs, s.rules, args)
        except PlanRefused as exc:
            return _refused(str(exc))
        await s.change(uid, lambda d: d.model_copy(update={"prefs": new}))
        return {"message": words}

    async def wear(self, args: dict[str, Any]) -> dict[str, Any]:
        got = await self._ready()
        if isinstance(got, dict):
            return got
        uid, here, doc, view = got
        pieces, why = self._pieces(doc, view, args, here)
        if why:
            return _refused(why)
        store = self.s.ctx.store()
        assert store is not None
        if args.get("action") == "start":
            bad = [
                i
                for i in pieces
                if not view.pieces[i].eligible and view.pieces[i].state != "in_use"
            ]  # noqa: E501
            if bad:
                return _refused(
                    f"{texts.states_line([view.pieces[i] for i in bad])}: it can't be worn now."
                )  # noqa: E501
            plan = args.get("plan") if doc.plan(str(args.get("plan"))) else None
            await wear.commit(
                store, uid, wear.start_events(view, pieces, plan, here.now, via=_via())
            )  # noqa: E501
            return {
                "pieces": pieces,
                "message": f"Noted: you're wearing {texts.ids_words([texts.unit_words([view.pieces[i]]) for i in pieces][:3])}{' and more' if len(pieces) > 3 else ''}.",
            }  # noqa: E501
        in_use = [i for i in pieces if view.pieces[i].state == "in_use"]
        if not in_use:
            return _refused("Nothing named is in use.")
        await wear.commit(
            store, uid, wear.done_events(view, in_use, self.s.rules, here.now, via=_via())
        )  # noqa: E501
        return {
            "pieces": in_use,
            "message": f"Done for today: {len(in_use)} pieces, one wear each.",
        }  # noqa: E501

    def _pieces(
        self, doc: Any, view: Any, args: dict[str, Any], here: Any
    ) -> tuple[list[str], str]:  # noqa: E501
        named = [str(i) for i in args.get("pieces") or []]
        if named:
            missing = [i for i in named if i not in view.pieces]
            return (
                (named, "")
                if not missing
                else ([], f"{texts.ids_words(missing)} isn't in your wardrobe.")
            )  # noqa: E501
        plan = doc.plan(str(args.get("plan"))) if args.get("plan") else None
        if plan is not None:
            return list(plan.pieces()), ""
        if args.get("query"):
            return wear.resolve(view, str(args["query"]))
        if args.get("action") == "done":
            return [
                p.id for p in sorted(view.active(), key=lambda x: x.id) if p.state == "in_use"
            ], ""  # noqa: E501
        return [], "Say which pieces, or the plan you are wearing."

    async def wear_card(self, args: dict[str, Any]) -> Preview:
        """A wear card's words: fixed words through `redact` ("a private basic")."""
        view = await self.s.view(_uid())
        doc = await self.s.plans.read(_uid()) if self.s.off() is None else None
        if view is None:
            return Preview("Log a wear.")
        pieces, _ = (
            self._pieces(doc, view, args, None)
            if doc is not None
            else ([str(i) for i in args.get("pieces") or []], "")
        )  # noqa: E501
        words = [card_words(view.pieces[i]) for i in pieces if i in view.pieces]
        return Preview(f"Log a wear: {texts.ids_words(words)}." if words else "Log a wear.")


def styling_tools(s: Styling) -> tuple[Tool, ...]:
    t = StylingTools(s)

    def plan_words(args: dict[str, Any]) -> str:
        return f"Outfit plan: {str(args.get('action', 'change'))[:12]}."

    def prefs_words(args: dict[str, Any]) -> str:
        return f"Outfit rule: {str(args.get('action', 'change'))[:12]}."

    return (
        Tool(
            "outfit_suggest",
            "What to wear on a day, by his fixed rules, with reasons and the piece ids.",
            SUGGEST,
            R1,
            t.suggest,
            agent=AGENT,
            may_vouch=True,
            activity_words="Looked at an outfit",
        ),  # noqa: E501
        Tool(
            "outfit_plans",
            "His outfit plans ahead (or one day's) and their looks now.",
            PLANS,
            R1,
            t.plans,
            agent=AGENT,
            may_vouch=True,
            activity_words="Looked at outfit plans",
        ),  # noqa: E501
        Tool(
            "outfit_plan",
            "Save, lock, change, reserve, transfer, release or share an outfit plan (piece ids).",
            PLAN,
            R2,
            t.plan,
            agent=AGENT,
            summarize=plan_words,
            activity_words="Changed an outfit plan",
        ),  # noqa: E501
        Tool(
            "outfit_prefs",
            "His outfit rules: never / allow, exclude / include, like / avoid colours, a plan's dress code.",
            PREFS,
            R2,
            t.prefs,
            agent=AGENT,
            summarize=prefs_words,
            activity_words="Changed an outfit rule",
        ),  # noqa: E501
        Tool(
            "wear_log",
            "Log a wear: start (I'm wearing ...) or done (I wore ... / done for today).",
            WEAR,
            R2,
            t.wear,
            agent=AGENT,
            spoken_ok=True,
            preview=t.wear_card,
            activity_words="Logged a wear",
        ),  # noqa: E501
    )


__all__ = ["AGENT", "StylingTools", "styling_tools"]
