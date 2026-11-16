# src/jarvis/wardrobe/redact.py
"""R13 D10 (docs/plans/r13-wardrobe.md): what each sink may show of a piece. Pure.

- `panel` (his signed-in console): everything; a private piece behind "Show private basics".
- `model` (tool results for the AI): id, his label (the caller fences it), type, colour, state,
  place; never an unverified field. A private piece: its id, slot and state ("a private basic").
- `alert` (alerts, Telegram, Web Push, the lock screen): fixed words ("a navy shirt"); a private
  piece "a private basic".
- `card` (approval cards: stored in clear, printed on Telegram): the same fixed words and the
  piece's number ("a private basic (No. 17)"); `Tool.preview` writes them through here.
- `bin` (Recently deleted: Firestore, in clear): "A wardrobe piece" for every piece.
- `log` (logs, the audit, Activity): its id only.

His label is never in an alert, a card's words, the bin, a log or the lock screen; an unverified
label field never reaches the model (INV-10). The needles eval (`evals/r13/needles.py`, I1) holds
every sink to this; its control swaps the model view for the panel view.
"""

from __future__ import annotations

from typing import Any, Literal

from jarvis.wardrobe.model import TYPES, Piece, Verified
from jarvis.wardrobe.states import STATE_WORDS

Sink = Literal["panel", "model", "alert", "card", "bin", "log"]
SINKS: tuple[Sink, ...] = ("panel", "model", "alert", "card", "bin", "log")
PRIVATE_WORDS = "a private basic"
BIN_TITLE = "A wardrobe piece"  # Recently deleted is Firestore, in clear: never a name
_SLOTS = {
    "underpants": "underwear",
    "briefs": "underwear",
    "boxers": "underwear",
    "vest": "base layer",
    "undershirt": "base layer",
    "thermal": "base layer",
}


_KNOWN = frozenset(t for types in TYPES.values() for t in types)


def type_words(piece: Piece) -> str:
    """The type in plain words from the fixed list ("t_shirt" -> "T-shirt"); a type he added
    (his own words) or "unknown" reads "piece" outside his panel."""
    if piece.type not in _KNOWN:
        return "piece"
    special = {"t_shirt": "T-shirt", "dress_shoe": "dress shoe", "work_gear": "work gear"}
    return special.get(piece.type, piece.type.replace("_", " "))


def fixed_words(piece: Piece) -> str:
    """ "a navy shirt": the colour and type words only (never his label); a private piece is
    "a private basic"."""
    if piece.private:
        return PRIVATE_WORDS
    colour = (piece.colour or "").replace("_", " ")
    return " ".join(w for w in ("a", colour, type_words(piece)) if w)


def _verified(v: Verified | None) -> str | None:
    return v.v if v is not None and v.ok else None


def model_view(piece: Piece, place_label: str | None = None) -> dict[str, Any]:
    """The AI's view (tool results): never an unverified field; a private piece is its slot."""
    if piece.private:
        slot = _SLOTS.get(piece.type, "base layer")
        return {"id": piece.id, "slot": slot, "state": piece.state, "words": PRIVATE_WORDS}
    out: dict[str, Any] = {
        "id": piece.id,
        "label": piece.label,  # his words: the caller fences them (wrap_external)
        "type": piece.type,
        "colour": piece.colour,
        "state": piece.state,
        "state_words": STATE_WORDS[piece.state],
        "place": place_label,
    }
    size = _verified(piece.size)
    if size is not None:
        out["size"] = size
    care = [c.v for c in piece.care if c.ok]
    if care:
        out["care"] = care
    return {k: v for k, v in out.items() if v not in (None, "")}


def alert_words(piece: Piece) -> str:
    """Alerts, Telegram, Web Push, the lock screen."""
    return fixed_words(piece)


def card_words(piece: Piece, number: int | None = None) -> str:
    """An approval card's words (`Tool.preview`), stored in clear and printed on Telegram."""
    base = fixed_words(piece)
    return f"{base} (No. {number})" if number is not None else base


def bin_title(piece: Piece) -> str:
    return BIN_TITLE


def log_view(piece: Piece) -> dict[str, str]:
    return {"piece": piece.id}


def view(piece: Piece, sink: Sink, *, number: int | None = None) -> Any:
    """One entry point for every sink (the needles eval walks them all)."""
    if sink == "panel":
        return piece.to_json()
    if sink == "model":
        return model_view(piece)
    if sink == "alert":
        return alert_words(piece)
    if sink == "card":
        return card_words(piece, number)
    if sink == "bin":
        return bin_title(piece)
    return log_view(piece)


__all__ = [
    "BIN_TITLE",
    "PRIVATE_WORDS",
    "SINKS",
    "Sink",
    "alert_words",
    "bin_title",
    "card_words",
    "fixed_words",
    "log_view",
    "model_view",
    "type_words",
    "view",
]
