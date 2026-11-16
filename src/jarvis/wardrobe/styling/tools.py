# src/jarvis/wardrobe/styling/tools.py
"""R13 Part C's five tools (docs/plans/r13-wardrobe.md "Tools", D10, D18). Every call passes the
gateway (policy, cards, the audit); the panel calls the same tools through A's
`POST /v1/wardrobe/tools/{tool}` (D1).

- `outfit_suggest` (R1, No-AI): a day's look ("today", "tomorrow" in his zone, or a date; an
  occasion in his words; a dress code): the day's plans of that occasion when it has some (for
  today, not worn and not over), else a suggestion; a dress code is always a fresh suggestion.
- `outfit_plans` (R1): the plans ahead (or one day's) with their looks now.
- `outfit_plan` (R2): save, lock, change, reserve, transfer, release, share (`actions`).
- `outfit_prefs` (R2): never / allow, exclude / include, like / avoid, a plan's dress code.
- `wear_log` (R2, `spoken_ok`, No-AI): start / done a wear (`wear`); pieces by id, a plan, or
  his words (`query`: D10's one exception).

Results: piece ids and fixed words only (`views`), at most 20 pieces; the two reads vouch for
their result (every string is a fixed-list word or JARVIS's own sentence, never his label or a
title, D18). A card's words come from `preview` through `redact` ("a private basic"). Untrusted
by default (`trusted_output` False); Activity shows fixed words.
"""

from __future__ import annotations

from typing import Any

from jarvis.core.guardrails import ActionRisk
from jarvis.tools.base import Tool
from jarvis.tools.provenance import vouch
from jarvis.wardrobe.model import WardrobeView
from jarvis.wardrobe.ports import MAX_RESULT_PIECES
from jarvis.wardrobe.styling import actions, prefs, views
from jarvis.wardrobe.styling.answers import plural, ready, refused
from jarvis.wardrobe.styling.plans import PlanRefused, StylingDoc
from jarvis.wardrobe.styling.service import Answer, Here, Styling
from jarvis.wardrobe.styling.wearlog import WearLog

AGENT = "outfits"
R1, R2 = ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE
LOOK_KEYS = ("pieces", "reasons", "compromises", "gaps")
_S: dict[str, Any] = {"type": "string"}
_IDS: dict[str, Any] = {"type": "array", "items": {"type": "string"}, "maxItems": 20}
CODES = "business_formal, business_casual, smart_casual, casual, festive, mess_tolerant, sport"
_SETTING: dict[str, Any] = {
    "type": "string", "enum": ["indoor", "outdoor"],
    "description": "indoor or outdoor (rain-ok shoes and an outer layer outdoors when rain)",
}  # fmt: skip
SETTINGS = {"indoor": False, "outdoor": True}


def _schema(props: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(required)}


SUGGEST = _schema(
    {
        "day": {**_S, "description": "today, tomorrow (his time zone) or YYYY-MM-DD"},
        "occasion": {**_S, "maxLength": 60, "description": "his words: the meeting, Diwali"},
        "code": {**_S, "description": f"a dress code: {CODES}"},
        "setting": _SETTING,
    }
)
PLANS = _schema({"day": _S, "days": {"type": "integer", "minimum": 1, "maximum": 14}})
PLAN = _schema(
    {
        "action": {"type": "string", "enum": list(actions.ACTIONS)},
        **dict.fromkeys(("plan", "day", "code", "start", "end", "slot", "piece", "from_plan"), _S),
        "occasion": {**_S, "maxLength": 60},
        "pieces": _IDS,
        "setting": _SETTING,
    },
    ("action",),
)
PREFS = _schema(
    {
        "action": {"type": "string", "enum": list(prefs.ACTIONS)},
        **dict.fromkeys(("feature", "value", "piece", "plan", "code"), _S),
        "occasion": {**_S, "maxLength": 60},
    },
    ("action",),
)
WEAR = _schema(
    {
        "action": {"type": "string", "enum": ["start", "done"]},
        "pieces": _IDS,
        "plan": _S,
        "query": {**_S, "maxLength": 80, "description": "his words (the spoken one-step path)"},
        "day": {**_S, "description": "done only: today, yesterday or YYYY-MM-DD (30 days back)"},
    },
    ("action",),
)


class StylingTools:
    def __init__(self, s: Styling) -> None:
        self.s = s

    def _entry(
        self, view: WardrobeView, ans: Answer, here: Here, budget: int
    ) -> tuple[dict[str, Any], int]:
        entry, used = views.answer_dict(view, ans, self.s.rules, here, budget=budget)
        if ans.plan is not None:
            entry = {"id": ans.plan.id, **entry, "look": {k: entry[k] for k in LOOK_KEYS}}
        return entry, used

    async def suggest(self, args: dict[str, Any]) -> Any:
        got = await ready(self.s)
        if isinstance(got, dict):
            return got
        uid, here, doc, view = got
        s = self.s
        day = s.day_of(args.get("day"), here.today)
        if day is None:
            return refused("Ask for today, tomorrow or a date up to 30 days ahead.")
        occ = s.rules.occasion_of(str(args["occasion"])) if args.get("occasion") else None
        code = args.get("code") if args.get("code") in s.rules.codes else None
        planned = s.planned(doc, day, here, occ) if code is None else ()
        answers = [await s.answer(uid, here, doc, view, p) for p in planned]
        if not answers:  # outdoors: his setting, else his words ("a walk in the park", M7)
            words = str(args.get("occasion") or "")
            out = SETTINGS.get(str(args.get("setting")), s.rules.outdoor_of(words))
            fresh = await s.fresh(uid, here, doc, view, day=day, occasion=occ, code=code, out=out)
            answers = [fresh]
        looks, budget = [], MAX_RESULT_PIECES
        for ans in answers:
            entry, used = views.answer_dict(view, ans, s.rules, here, budget=budget)
            looks.append(entry)
            budget -= used
        first = answers[0]
        out = {
            "day": day.isoformat(),
            "message": views.message(view, first, s.rules, here),
            "looks": looks,
            "alternatives": views.alternatives(view, first, budget),
        }
        return vouch(out, True)

    async def plans(self, args: dict[str, Any]) -> Any:
        got = await ready(self.s)
        if isinstance(got, dict):
            return got
        uid, here, doc, view = got
        day = self.s.day_of(args["day"], here.today) if args.get("day") else None
        days = int(args.get("days") or 7)
        if day is not None:
            found = [p for p in doc.plans if p.day == day]
        else:
            found = [p for p in doc.plans if 0 <= (p.day - here.today).days < days]
        out, budget = [], MAX_RESULT_PIECES
        for p in found:
            ans = await self.s.answer(uid, here, doc, view, p)
            entry, used = self._entry(view, ans, here, budget)
            out.append(entry)
            budget -= used
        return vouch({"plans": out, "message": f"{plural(len(out), 'plan')}."}, True)

    async def _plan_dict(self, uid: str, pid: str) -> dict[str, Any]:
        s = self.s
        here, doc, view = await s.where(uid), await s.plans.read(uid), await s.view(uid)
        plan = doc.plan(pid)
        assert plan is not None and view is not None
        ans = await s.answer(uid, here, doc, view, plan)
        return self._entry(view, ans, here, MAX_RESULT_PIECES)[0]

    async def plan(self, args: dict[str, Any]) -> dict[str, Any]:
        got = await ready(self.s)
        if isinstance(got, dict):
            return got
        try:
            plan, words = await actions.run(self.s, got[0], args)
        except PlanRefused as exc:
            return refused(str(exc))
        if plan is None:
            return {"message": words}
        return {"message": words, "plan": await self._plan_dict(got[0], plan.id)}

    async def prefs(self, args: dict[str, Any]) -> dict[str, Any]:
        got = await ready(self.s)
        if isinstance(got, dict):
            return got
        uid, here, doc, view = got
        try:
            if args.get("action") == "code":
                return await self._code(uid, here, doc, view, args)
            new, words = prefs.apply(doc.prefs, self.s.rules, args)
        except PlanRefused as exc:
            return refused(str(exc))
        await self.s.change(uid, lambda d: d.model_copy(update={"prefs": new}))
        return {"message": words}

    async def _code(
        self, uid: str, here: Here, doc: StylingDoc, view: WardrobeView, args: dict[str, Any]
    ) -> dict[str, Any]:
        s = self.s
        fixed = prefs.set_code(doc, s.rules, args.get("plan"), args.get("code"))
        plan = fixed.plan(str(args["plan"]))
        assert plan is not None
        plan = await s.repick(uid, here, fixed, view, plan)
        await s.change(uid, lambda d: d.put(plan))
        words = f"Dress code set: {s.rules.code_words(plan.code)}."
        return {"message": words, "plan": await self._plan_dict(uid, plan.id)}


def _plan_words(args: dict[str, Any]) -> str:
    return f"Outfit plan: {str(args.get('action', 'change'))[:12]}."


def _prefs_words(args: dict[str, Any]) -> str:
    return f"Outfit rule: {str(args.get('action', 'change'))[:12]}."


def styling_tools(s: Styling) -> tuple[Tool, ...]:
    t, w = StylingTools(s), WearLog(s)
    return (
        Tool(
            "outfit_suggest",
            "What to wear on a day, by his fixed rules, with reasons and the piece ids.",
            SUGGEST, R1, t.suggest, agent=AGENT, may_vouch=True,
            activity_words="Looked at an outfit",
        ),
        Tool(
            "outfit_plans",
            "His outfit plans ahead (or one day's) and their looks now.",
            PLANS, R1, t.plans, agent=AGENT, may_vouch=True,
            activity_words="Looked at outfit plans",
        ),
        Tool(
            "outfit_plan",
            "Save, lock, change, reserve, transfer, release or share an outfit plan (piece ids).",
            PLAN, R2, t.plan, agent=AGENT, summarize=_plan_words,
            activity_words="Changed an outfit plan",
        ),
        Tool(
            "outfit_prefs",
            "His outfit rules: never or allow, exclude or include, like or avoid, a dress code.",
            PREFS, R2, t.prefs, agent=AGENT, summarize=_prefs_words,
            activity_words="Changed an outfit rule",
        ),
        Tool(
            "wear_log",
            "Log a wear: start (I'm wearing ...) or done (I wore ..., done for today).",
            WEAR, R2, w.run, agent=AGENT, spoken_ok=True, preview=w.card,
            activity_words="Logged a wear",
        ),
    )  # fmt: skip


__all__ = ["AGENT", "StylingTools", "styling_tools"]
