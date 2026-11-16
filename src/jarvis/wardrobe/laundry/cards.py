# src/jarvis/wardrobe/laundry/cards.py
"""R13 Part B: what the model and an approval card see (docs/plans/r13-wardrobe.md D10).

- `shown(view, pid)`: a piece in a tool result: `redact.model_view` (never an unverified field; a
  private piece is its slot and "a private basic"), his label fenced as external data (masked on
  a spoken or Telegram turn).
- `fence(text)`: his words (a label, a shop's label) fenced for the model.
- `move` / `review` / `correct` / `send`: a card's words, from the piece records through
  `redact.fixed_words`; never his label, the shop's label or the `query` he typed (a card is
  stored in clear and printed on Telegram). A look-up that finds nothing still writes a card
  ("none matches yet"): a preview never fails for content.
"""

from __future__ import annotations

from typing import Any

from jarvis.tools.card import one_line
from jarvis.tools.external import wrap_external
from jarvis.tools.spoken import mask_for_speech, speaking_now, withhold_if_sensitive
from jarvis.wardrobe.laundry import blind, checks, texts
from jarvis.wardrobe.laundry.holds import resolve_query
from jarvis.wardrobe.model import LABEL_MAX, Piece, WardrobeView
from jarvis.wardrobe.ports import Refused
from jarvis.wardrobe.redact import fixed_words, model_view

SOURCE = "your wardrobe"
GENERIC = "Record a laundry step for wardrobe pieces"
_OUTCOME = {
    "these": "Answer a laundry check",
    "none": "Answer a laundry check: it didn't happen",
    "moved": "Answer a laundry check: it is somewhere else now",
    "dismiss": "Close a laundry check",
}


def fence(text: str) -> str:
    plain = one_line(text, LABEL_MAX)
    if speaking_now():
        plain = withhold_if_sensitive(mask_for_speech(plain))
    return wrap_external(plain, source=SOURCE, limit=LABEL_MAX)


def fenced(out: dict[str, Any]) -> dict[str, Any]:
    """A `model_view` with his words (the label, the place's label) fenced, masked when spoken."""
    return {k: fence(v) if k in ("label", "place") and v else v for k, v in out.items()}


def shown(view: WardrobeView, pid: str) -> dict[str, Any]:
    p = view.pieces.get(pid)
    if p is None:
        return {"id": pid}
    place = view.places.get(p.place or "")
    return fenced(model_view(p, place.label if place else None))


def _pieces(view: WardrobeView, ids: Any) -> list[Piece]:
    return [view.pieces[i] for i in (ids or []) if isinstance(i, str) and i in view.pieces]


def move(view: WardrobeView | None, a: dict[str, Any]) -> str:
    step = a.get("step", "basket")
    if view is None or step not in checks.STEPS:
        return GENERIC
    pieces, cands = _pieces(view, a.get("pieces")), _pieces(view, a.get("one_of"))
    if a.get("query"):
        try:
            hit = resolve_query(view, step, a["query"])
        except Refused:
            hit = ()
        found = _pieces(view, hit)
        pieces, cands = (pieces + found, cands) if len(found) == 1 else (pieces, found or cands)
    more = a.get("more") or 0
    if pieces:
        base = texts.card(step, pieces)
        return f"{base}, and {more} more you couldn't show" if more else base
    if cands:
        return texts.card_one_of(step, len(cands))
    if more:
        return f"Note {texts.count_words(more)} in the laundry basket that you couldn't show"
    if a.get("load"):
        return texts.card_load(step)
    return f"{GENERIC} (none matches yet)"


def review(view: WardrobeView | None, a: dict[str, Any]) -> str:
    action = a.get("action", "list")
    if action == "list":
        return "List the laundry checks"
    if action == "blind":
        try:
            n = (
                len(blind.touched(view, a.get("places") or (), a.get("categories") or ()))
                if view
                else 0
            )
        except Refused:
            n = 0
        return f"Hold {texts.count_words(n)} for a quick check: moved without a scan"
    base = _OUTCOME.get(a.get("outcome", "these"), _OUTCOME["these"])
    pieces = _pieces(view, a.get("pieces")) if view else []
    return f"{base} about {texts.names(pieces)}" if pieces else base


def correct(view: WardrobeView | None, a: dict[str, Any]) -> str:
    p = view.pieces.get(a.get("piece", "")) if view else None
    return (
        f"Strike out a recorded laundry step for {fixed_words(p)}"
        if p
        else ("Strike out a recorded laundry step")
    )


def send(view: WardrobeView | None, a: dict[str, Any]) -> str:
    pieces = _pieces(view, a.get("pieces")) if view else []
    what = texts.names(pieces) if pieces else "wardrobe pieces"
    if a.get("action", "send") == "receive":
        return f"Note that {what} came back from an outside laundry"
    try:
        due = checks.due_of(a)
    except ValueError:
        due = None
    when = f", due {texts.day_words(due)}" if due else ""
    return f"Note that {what} went to an outside laundry{when}"


__all__ = ["GENERIC", "SOURCE", "correct", "fence", "fenced", "move", "review", "send", "shown"]
