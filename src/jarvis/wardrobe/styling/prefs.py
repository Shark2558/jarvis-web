# src/jarvis/wardrobe/styling/prefs.py
"""R13 STY-03, STY-06, STY-08 (docs/plans/r13-wardrobe.md D12): his own outfit rules, pure.

- `never` / `allow`: a "never" rule on a fixed feature word ("never tight at the neck": `neck`
  `tight`, from `model.FEATURES`; or a colour, a pattern or a type from the fixed lists), at most
  20; `allow` removes one. A rule that leaves a slot empty is named in that look's gap (STY-08).
- `exclude` / `include`: a piece kept out of one occasion's looks ("my favourite shirt never for
  Holi", STY-06) or out of all of them.
- `like` / `avoid`: colours he prefers or avoids (ranking only, never an exclusion).
- `code`: the dress code of one plan, set by him (no longer tentative, STY-03); the calendar is
  never written.
Every word is a fixed-list word or a piece id: nothing here holds his free text.
"""

from __future__ import annotations

from typing import Any

from jarvis.wardrobe.model import COLOURS, FEATURES, PATTERNS, PIECE_ID, TYPES
from jarvis.wardrobe.styling import texts
from jarvis.wardrobe.styling.plans import (
    MAX_COLOURS,
    MAX_EXCLUDED,
    MAX_NEVER,
    Exclusion,
    Never,
    PlanRefused,
    Prefs,
    StylingDoc,
)
from jarvis.wardrobe.styling.rules import Rules

ACTIONS = ("never", "allow", "exclude", "include", "like", "avoid", "code")
BY_ID = "Name the piece by its id (wi_ and 12 letters or digits)."
_TYPES = tuple(t for ts in TYPES.values() for t in ts)
FIXED: dict[str, tuple[str, ...]] = {
    **{k: v for k, v in FEATURES.items() if k != "side"},
    "colour": tuple(COLOURS),
    "pattern": PATTERNS,
    "type": _TYPES,
}


def rule_of(feature: Any, value: Any) -> Never:
    if feature not in FIXED or value not in FIXED[feature]:
        raise PlanRefused("A rule takes a fixed word: like neck and tight, or colour and orange.")
    return Never(feature=feature, value=value)


def _occasion(rules: Rules, occasion: Any) -> str | None:
    if occasion in (None, ""):
        return None
    if isinstance(occasion, str):
        found = occasion if occasion in rules.events else rules.occasion_of(occasion)
        if found is not None:
            return found
    raise PlanRefused(
        "That occasion isn't one JARVIS knows: a meeting, a festival, Holi, sport or a function."
    )


def apply(prefs: Prefs, rules: Rules, args: dict[str, Any]) -> tuple[Prefs, str]:
    """(his rules after `args`, what changed in words)."""
    action = args.get("action")
    if action in ("never", "allow"):
        rule = rule_of(args.get("feature"), args.get("value"))
        words = texts.never_words(rule.feature, rule.value)
        rest = tuple(n for n in prefs.never if n != rule)
        if action == "allow":
            return prefs.model_copy(update={"never": rest}), f'Removed your rule "never {words}".'
        if len(rest) >= MAX_NEVER:
            raise PlanRefused(f"You have {MAX_NEVER} rules: remove one first.")
        return prefs.model_copy(update={"never": (*rest, rule)}), f"Noted: never {words}."
    if action in ("exclude", "include"):
        piece = args.get("piece")
        if not isinstance(piece, str) or not PIECE_ID.match(piece):  # never echoed (M2)
            raise PlanRefused(BY_ID)
        occ = _occasion(rules, args.get("occasion"))
        kept = tuple(e for e in prefs.excluded if not (e.piece == piece and e.occasion == occ))
        where = f"for {texts.OCCASION_WORDS[occ]}" if occ else "from every look"
        if action == "include":
            return prefs.model_copy(update={"excluded": kept}), f"{piece} is back {where}."
        if len(kept) >= MAX_EXCLUDED:
            raise PlanRefused(f"You have {MAX_EXCLUDED} exclusions: remove one first.")
        out = (*kept, Exclusion(piece=piece, occasion=occ))
        return prefs.model_copy(update={"excluded": out}), f"{piece} is left out {where}."
    colour = args.get("value")
    if action in ("like", "avoid") and colour in COLOURS:
        likes = tuple(c for c in prefs.likes if c != colour)
        avoids = tuple(c for c in prefs.avoids if c != colour)
        if action == "like":
            likes = (*likes, colour)[-MAX_COLOURS:]
        else:
            avoids = (*avoids, colour)[-MAX_COLOURS:]
        word = str(colour).replace("_", " ")
        return prefs.model_copy(
            update={"likes": likes, "avoids": avoids}
        ), f"Noted: you {action} {word}."
    raise PlanRefused("Say never, allow, exclude, include, like, avoid or code.")


def set_code(doc: StylingDoc, rules: Rules, plan_id: Any, code: Any) -> StylingDoc:
    plan = doc.plan(plan_id) if isinstance(plan_id, str) else None
    if plan is None:
        raise PlanRefused("That plan isn't there any more.")
    if code not in rules.codes:
        raise PlanRefused("That isn't one of the dress codes.")
    fixed = plan.model_copy(
        update={"code": code, "tentative": False, "picks": tuple(p for p in plan.picks if p.locked)}
    )
    return doc.put(fixed)


__all__ = ["ACTIONS", "FIXED", "apply", "rule_of", "set_code"]
