# src/jarvis/wardrobe/styling/cards.py
"""R13 Part C's write tools' cards and argument checks (D10, D16, D18; security review 1 M2, M4,
L2, L3).

- `check_*`: pure checks the gateway runs BEFORE the policy step (`Tool.check`): each action is
  one of the tool's, an id matches its pattern, at most 20 different piece ids, text is short,
  `days` is 1 to 14, an occasion on the write tools is one of the rules' keys (never his free
  words in a card's stored arguments). A refusal is `ValueError` in fixed words that never echo
  the argument (the gateway shows it to the model and writes it to the audit).
- `plan_words` / `prefs_words`: the fixed summaries (never the model's raw `action`).
- `Cards.plan` / `Cards.prefs`: the read-only previews a card shows (`Tool.preview`): the plan by
  its day and time ("tomorrow's 10:00 outfit"), a piece by its fixed words through
  `redact.card_words` ("a private basic"); anything it can't read falls back to the fixed
  summary, so a preview never fails the call.
- `whole_release`: removing a whole plan is always a card (`Tool.ask_when`).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Any

from jarvis.tools.base import CheckFn, Preview
from jarvis.wardrobe.model import PIECE_ID, WardrobeView
from jarvis.wardrobe.ports import MAX_RESULT_PIECES
from jarvis.wardrobe.redact import card_words
from jarvis.wardrobe.styling import actions, prefs, texts
from jarvis.wardrobe.styling.answers import uid
from jarvis.wardrobe.styling.plans import PLAN_ID, Plan
from jarvis.wardrobe.styling.reserve import unit_of
from jarvis.wardrobe.styling.rules import Rules
from jarvis.wardrobe.styling.service import Here, Styling

SHORT, OCCASION_MAX, QUERY_MAX = 24, 60, 80
SETTINGS = ("indoor", "outdoor")
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
PLAN_WORDS = {
    "save": "Save an outfit plan",
    "lock": "Lock a piece of an outfit plan",
    "change": "Change one piece of an outfit plan",
    "reserve": "Reserve a piece for an outfit plan",
    "transfer": "Move a piece between outfit plans",
    "release": "Take a piece out of an outfit plan",
    "share": "Share pieces between outfit plans",
}
PREFS_WORDS = {
    "never": "Add an outfit rule", "allow": "Remove an outfit rule",
    "exclude": "Leave a piece out of looks", "include": "Bring a piece back into looks",
    "like": "Prefer a colour in looks", "avoid": "Avoid a colour in looks",
    "code": "Set an outfit plan's dress code",
}  # fmt: skip


# ---- the checks (pure, fixed words) ---------------------------------------------------------
def _text(args: dict[str, Any], key: str, limit: int) -> None:
    v = args.get(key)
    if v is not None and (not isinstance(v, str) or len(v) > limit):
        raise ValueError(f"{key} must be text of at most {limit} characters.")


def _one_of(args: dict[str, Any], key: str, allowed: Sequence[str]) -> None:
    v = args.get(key)
    if v is not None and v not in allowed:
        raise ValueError(f"{key} must be one of: {', '.join(allowed)}.")


def _id(args: dict[str, Any], key: str, rx: re.Pattern[str], like: str) -> None:
    v = args.get(key)
    if v is not None and (not isinstance(v, str) or not rx.match(v)):
        raise ValueError(f"{key} must be an id like {like}.")


def _pieces(args: dict[str, Any]) -> None:
    v = args.get("pieces")
    if v is None:
        return
    good = isinstance(v, list) and all(isinstance(i, str) and PIECE_ID.match(i) for i in v)
    if not good or len(v) > MAX_RESULT_PIECES or len(set(v)) != len(v):
        raise ValueError("pieces must be at most 20 different piece ids (wi_ and 12 letters).")


def _common(args: dict[str, Any], *texts_: str) -> None:
    _id(args, "plan", PLAN_ID, "op_ and 8 letters")
    _id(args, "from_plan", PLAN_ID, "op_ and 8 letters")
    _id(args, "piece", PIECE_ID, "wi_ and 12 letters")
    _pieces(args)
    for key in texts_:
        _text(args, key, SHORT)


def check_suggest(args: dict[str, Any]) -> None:
    _common(args, "day", "code")
    _text(args, "occasion", OCCASION_MAX)
    _one_of(args, "setting", SETTINGS)


def check_plans(args: dict[str, Any]) -> None:
    _common(args, "day")
    v = args.get("days")
    if v is not None and (isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 14):
        raise ValueError("days must be a whole number from 1 to 14.")


def check_plan(occasions: Sequence[str]) -> CheckFn:
    def check(args: dict[str, Any]) -> None:
        _one_of(args, "action", actions.ACTIONS)
        _common(args, "day", "code", "slot", "start", "end")
        _one_of(args, "occasion", occasions)
        _one_of(args, "setting", SETTINGS)

    return check


def check_prefs(occasions: Sequence[str]) -> CheckFn:
    def check(args: dict[str, Any]) -> None:
        _one_of(args, "action", prefs.ACTIONS)
        _common(args, "feature", "value", "code")
        _one_of(args, "occasion", occasions)

    return check


def check_wear(args: dict[str, Any]) -> None:
    _one_of(args, "action", ("start", "done"))
    _common(args, "day")
    _text(args, "query", QUERY_MAX)


# ---- the fixed summaries and the always-a-card rule ---------------------------------------------
def whole_release(args: dict[str, Any]) -> bool:
    return args.get("action") == "release" and not args.get("piece")


def plan_words(args: dict[str, Any]) -> str:
    if whole_release(args):
        return "Remove an outfit plan."
    return f"{PLAN_WORDS.get(str(args.get('action')), 'Change an outfit plan')}."


def prefs_words(args: dict[str, Any]) -> str:
    return f"{PREFS_WORDS.get(str(args.get('action')), 'Change an outfit rule')}."


# ---- the previews (read-only; never fail the call) -----------------------------------------------
Words = Callable[[dict[str, Any], Here, Any, WardrobeView, Rules], str | None]


class Cards:
    def __init__(self, s: Styling) -> None:
        self.s = s

    async def plan(self, args: dict[str, Any]) -> Preview:
        return Preview(await self._words(args, _plan_card) or plan_words(args))

    async def prefs(self, args: dict[str, Any]) -> Preview:
        return Preview(await self._words(args, _prefs_card) or prefs_words(args))

    async def _words(self, args: dict[str, Any], words: Words) -> str | None:
        try:
            if self.s.off() is not None:
                return None
            who = uid()
            view = await self.s.view(who)
            if view is None:
                return None
            here, doc = await self.s.where(who), await self.s.plans.read(who)
            return words(args, here, doc, view, self.s.rules)
        except Exception:  # noqa: BLE001 - a card falls back to its fixed words, never fails
            return None


def _label(plan: Plan | None, here: Here) -> str | None:
    if plan is None:
        return None
    return texts.outfit_label(plan.day, here.today, plan.starts, here.zone)


def _piece(view: WardrobeView, pid: Any) -> str | None:
    if not isinstance(pid, str) or pid not in view.pieces:
        return None
    unit = [view.pieces[i] for i in unit_of(view, pid)]
    if len(unit) == 2 and not any(p.private for p in unit):
        return texts.unit_words(unit)  # "a pair of brown dress shoes": fixed words only
    return card_words(view.pieces[pid])


def _plan_card(
    a: dict[str, Any], here: Here, doc: Any, view: WardrobeView, rules: Rules
) -> str | None:
    action, label = a.get("action"), _label(doc.plan(str(a.get("plan"))), here)
    piece = _piece(view, a.get("piece"))
    if action == "save":
        return _save_card(a, here, label)
    if label is None:
        return None
    if whole_release(a):
        return f"Remove {label} plan."
    slot = rules.slot_words_of(a["slot"]) if a.get("slot") in rules.slots else None
    by_piece = {
        "lock": f"Lock {piece} in {label}.",
        "reserve": f"Reserve {piece} for {label}.",
        "transfer": f"Move {piece} to {label}.",
        "release": f"Take {piece} out of {label}.",
    }
    if piece is not None and action in by_piece:
        return by_piece[str(action)]
    if slot is not None and action in ("lock", "change"):
        return f"{str(action).capitalize()} the {slot} of {label}."
    source = _label(doc.plan(str(a.get("from_plan"))), here)
    if action == "share" and source is not None and isinstance(a.get("pieces"), list):
        return f"Share {len(a['pieces'])} pieces of {source} with {label}."
    return None


def _save_card(a: dict[str, Any], here: Here, label: str | None) -> str | None:
    setting = a.get("setting") if a.get("setting") in SETTINGS else None
    if a.get("plan"):
        if label is None:
            return None
        return f"Mark {label} {setting}s." if setting else f"Save {label} again."
    day = Styling.day_of(a.get("day"), here.today)
    if day is None:
        return None
    at = f", {a['start']}" if isinstance(a.get("start"), str) and HHMM.match(a["start"]) else ""
    return f"Save an outfit plan for {texts.date_words(day)}{at}."


def _prefs_card(
    a: dict[str, Any], here: Here, doc: Any, view: WardrobeView, rules: Rules
) -> str | None:
    action = a.get("action")
    if action in ("never", "allow"):
        rule = prefs.rule_of(a.get("feature"), a.get("value"))  # fixed words, or it raises
        verb = "Add" if action == "never" else "Remove"
        return f'{verb} the rule "never {texts.never_words(rule.feature, rule.value)}".'
    if action in ("exclude", "include"):
        piece = _piece(view, a.get("piece"))
        occ = texts.LOOK_WORDS.get(str(a.get("occasion")))
        if piece is None:
            return None
        if action == "exclude":
            return f"Leave {piece} out of {f'{occ} looks' if occ else 'every look'}."
        return f"Bring {piece} back into {f'{occ} looks' if occ else 'every look'}."
    if action in ("like", "avoid") and a.get("value") in prefs.FIXED["colour"]:
        colour = str(a["value"]).replace("_", " ")
        return f"{'Prefer' if action == 'like' else 'Avoid'} {colour} in looks."
    label, code = _label(doc.plan(str(a.get("plan"))), here), a.get("code")
    if action == "code" and label is not None and isinstance(code, str) and code in rules.codes:
        return f"Set {label} to {rules.code_words(code)}."
    return None


__all__ = [
    "PLAN_WORDS",
    "PREFS_WORDS",
    "Cards",
    "check_plan",
    "check_plans",
    "check_prefs",
    "check_suggest",
    "check_wear",
    "plan_words",
    "prefs_words",
    "whole_release",
]
