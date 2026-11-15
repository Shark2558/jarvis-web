# src/jarvis/wardrobe/styling/views.py
"""R13 Part C's views (D10, the HTTP contract): what a look shows in each sink.

- `look_dict` / `answer_dict` (tool results for the model): piece ids and fixed words only ("a
  navy shirt"; a private piece "a private basic"), never his label, never a title; at most 20
  pieces a result (`MAX_RESULT_PIECES`: the alternatives are cut first, then later looks).
- `message(...)`: the one sentence No-AI mode shows ("Tomorrow, Tuesday 17 November: casual, no
  event planned. Weather unknown: I assumed indoors. Wear: ...").
- `plan_view` / `slot_picks` (GET /v1/outfits, his own panel): the same words; a private piece's
  colour and type only when he has tapped "Show private basics" (A's index setting).
"""

from __future__ import annotations

from datetime import tzinfo
from typing import Any

from jarvis.wardrobe import http
from jarvis.wardrobe.model import WardrobeView
from jarvis.wardrobe.ports import MAX_RESULT_PIECES
from jarvis.wardrobe.styling import texts
from jarvis.wardrobe.styling.engine import LookOut
from jarvis.wardrobe.styling.service import NO_EVENT, Answer, Here
from jarvis.wardrobe.styling.rules import Rules

SEE = f"See this look {texts.WHERE}."


def _words(view: WardrobeView, ids: tuple[str, ...]) -> str:
    return texts.unit_words([view.pieces[i] for i in ids if i in view.pieces])


def look_dict(view: WardrobeView, look: LookOut, *, budget: int) -> tuple[dict[str, Any], int]:
    """A look for the model, if it fits in `budget` pieces (else its words only)."""
    n = len(look.ids())
    if n > budget:
        return {"pieces": [], "reasons": [SEE], "compromises": [], "gaps": list(look.gaps)}, 0
    pieces = [
        {"slot": p.slot, "ids": list(p.pieces), "words": _words(view, p.pieces)} for p in look.picks
    ]  # noqa: E501
    out = {"pieces": pieces, "reasons": list(look.reasons), "compromises": list(look.compromises),
           "gaps": list(look.gaps)}  # fmt: skip
    return out, n


def answer_dict(
    view: WardrobeView, ans: Answer, rules: Rules, here: Here, *, budget: int = MAX_RESULT_PIECES
) -> tuple[dict[str, Any], int]:
    look, used = look_dict(view, ans.suggestion.primary, budget=budget)
    plan = ans.plan
    out = {
        "plan": plan.id if plan else None,
        "day": ans.day.isoformat(),
        "day_words": texts.day_words(ans.day, here.today),
        "occasion": ans.phrase or NO_EVENT,
        "code": ans.code,
        "code_words": rules.code_words(ans.code),
        "tentative": plan.tentative if plan else True,
        "weather": ans.weather.words,
        **look,
    }
    if plan is not None:
        out.update({"needs": [need_words(rules, s) for s in plan.needs], "manual": plan.manual,
                    "cancelled": plan.cancelled, "worn": plan.worn})  # fmt: skip
    return out, used


def alternatives(view: WardrobeView, ans: Answer, budget: int) -> list[dict[str, Any]]:
    out = []
    for alt in ans.suggestion.alternatives:
        got, used = look_dict(view, alt, budget=budget)
        if not used:
            break
        out.append(got)
        budget -= used
    return out


def need_words(rules: Rules, slot: str) -> str:
    return f"needs a new {rules.slot_words_of(slot)}"


def head(ans: Answer, rules: Rules, here: Here) -> str:
    code = rules.code_words(ans.code)
    tail = f" for {ans.phrase}" if ans.phrase else f", {NO_EVENT}"
    return f"{texts.day_words(ans.day, here.today)}: {code}{tail}."


def message(view: WardrobeView, ans: Answer, rules: Rules, here: Here) -> str:
    look = ans.suggestion.primary
    wear = [_words(view, p.pieces) for p in look.picks]
    parts = [head(ans, rules, here), ans.weather.words]
    if wear:
        parts.append(f"Wear: {texts.ids_words(wear)}.")
    if look.gaps:
        parts.append(look.gaps[0])
    return " ".join(parts)


# ---- the panel (GET /v1/outfits) -----------------------------------------------------------
def slot_picks(
    view: WardrobeView, look: LookOut, *, show_private: bool
) -> tuple[http.SlotPick, ...]:  # noqa: E501
    out = []
    for p in look.picks:
        for pid in p.pieces:
            piece = view.pieces.get(pid)
            if piece is None:
                continue
            words = (
                texts.private_view_words(piece)
                if piece.private and show_private
                else texts.piece_words(piece)
            )  # noqa: E501
            out.append(http.SlotPick(slot=p.slot, piece=pid, words=words, locked=p.locked))
    return tuple(out)


def panel_look(view: WardrobeView, look: LookOut, *, show_private: bool) -> http.Look:
    return http.Look(
        pieces=slot_picks(view, look, show_private=show_private),
        reasons=look.reasons, compromises=look.compromises, gaps=look.gaps,
    )  # fmt: skip


def plan_view(
    view: WardrobeView, ans: Answer, rules: Rules, zone: tzinfo, *, show_private: bool
) -> http.PlanView:
    plan = ans.plan
    look = panel_look(view, ans.suggestion.primary, show_private=show_private)
    if plan is None:
        return http.PlanView(id="suggestion", day=ans.day, dress_code=ans.code, look=look)
    return http.PlanView(
        id=plan.id, day=plan.day, event=plan.event, starts=plan.starts, dress_code=plan.code,
        tentative=plan.tentative, look=look, needs=tuple(need_words(rules, s) for s in plan.needs),
        manual=plan.manual, cancelled=plan.cancelled,
    )  # fmt: skip


__all__ = [
    "alternatives",
    "answer_dict",
    "head",
    "look_dict",
    "message",
    "need_words",
    "panel_look",
    "plan_view",
    "slot_picks",
]
