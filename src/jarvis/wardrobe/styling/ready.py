# src/jarvis/wardrobe/styling/ready.py
"""R13 D20's readiness rule, in ONE place (R13.1 integrated code review M5).

R13's `outfit_plan` refuses a piece that isn't ready (`actions.unready`: the guarantee), and
R13.1's figure says why a piece is a draft before any tool call (`tryon.options.blocker` and
`tryon.confirm.words_of`: the early check and its words). Both read the rule here, so a piece can
never be Ready on the figure and refused by the plan, or the reverse (D20: "the early check is for
the words; the tool's own check is the guarantee").

- `fits(rules, plan, p)`: Ready by the engine's rule (`Piece.eligible`), or `handed`;
- `handed(rules, plan, p)`: an In-use piece is fine only as the plan's declared shared base, from
  the very plan it is worn for, and reusable (STY-13);
- `broken_set(view, pid)`: the set a part can't be worn without, while that set isn't whole
  (STY-16), else None;
- `the(p)`, `verb(p)`, `state_words(p)`: "The navy jacket", "is" or "are", "is in the laundry"
  (fixed words, never his label; `STATE_WORDS` per state).
"""

from __future__ import annotations

from jarvis.wardrobe.model import Piece, WardrobeView
from jarvis.wardrobe.styling import texts
from jarvis.wardrobe.styling.look import sets_of, whole
from jarvis.wardrobe.styling.plans import Plan
from jarvis.wardrobe.styling.rules import Rules

STATE_WORDS: dict[str, str] = {
    "in_laundry": "{is} in the laundry", "washing": "{is} in the laundry",
    "drying": "{is} in the laundry", "needs_prep": "needs pressing",
    "with_provider": "{is} at the laundry shop", "needs_repair": "needs a repair",
    "review": "needs a quick check", "in_use": "{is} in use", "archived": "{is} archived",
}  # fmt: skip


def handed(rules: Rules, plan: Plan | None, p: Piece) -> bool:
    """In use for the very plan this one declared its shared base from, and reusable (STY-13)."""
    if plan is None or plan.shared_from is None or p.id not in plan.shared:
        return False
    return p.state == "in_use" and p.wear == plan.shared_from and rules.reusable_piece(p)


def fits(rules: Rules, plan: Plan | None, p: Piece) -> bool:
    """Ready by the engine's own rule for this plan (no plan: Ready only)."""
    return p.eligible or handed(rules, plan, p)


def broken_set(view: WardrobeView, pid: str) -> str | None:
    """The set `pid` can't be worn without, when that set isn't whole now, else None."""
    for sid, parts in sets_of(view, pid):
        if not dict(parts).get(pid, True) and not whole(view, parts):
            return sid
    return None


def the(p: Piece) -> str:
    """ "The navy jacket": fixed words, never his label."""
    words = texts.piece_words(p)
    return "The " + (words[2:] if words.startswith("a ") else words)


def verb(p: Piece) -> str:
    return "are" if p.type in texts.PLURAL_TYPES and not p.private else "is"


def state_words(p: Piece) -> str:
    """ "is in the laundry", "are in use", "needs pressing": why the piece isn't ready."""
    return STATE_WORDS.get(p.state, "{is} not ready").replace("{is}", verb(p))


__all__ = ["STATE_WORDS", "broken_set", "fits", "handed", "state_words", "the", "verb"]
