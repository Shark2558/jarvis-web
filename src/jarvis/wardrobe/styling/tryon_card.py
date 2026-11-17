# src/jarvis/wardrobe/styling/tryon_card.py
"""R13.1 row 388 (docs/plans/r13-1-try-on.md D21): when he asks what to wear, JARVIS decides by
R13's rules and the try-on card opens by itself with the look on his 3D figure.

`outfit_suggest` calls `show` with the first answer while Try-on is on: one `TryOnCard` beside
the reply (the day, the plan when one answered, the dress code, the primary look's slot -> piece
ids). A private slot, or a slot holding a private piece, is covered: its id never goes on the card
(AVT-14). Outside a collecting reply (a script, Telegram's text) nothing is shown. The card is
never in what the AI reads; the console (`console-tryon-card.js`, Part D) draws the figure dressed
in exactly these pieces, or the AVT-15 checklist when 3D can't run.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence

from pydantic import ValidationError

from jarvis.tools.reply_cards import TryOnCard, TryOnSlot, add_card
from jarvis.wardrobe.model import WardrobeView
from jarvis.wardrobe.styling.look import PRIVATE_SLOTS, Pick
from jarvis.wardrobe.styling.service import Answer

log = logging.getLogger(__name__)
CODE = re.compile(r"[a-z_]{0,30}")
MAX_SLOTS = 12


def _covered(view: WardrobeView, pick: Pick) -> bool:
    if pick.slot in PRIVATE_SLOTS:
        return True
    return any((p := view.piece(i)) is None or p.private for i in pick.pieces)


def _slot(view: WardrobeView, pick: Pick) -> TryOnSlot:
    if _covered(view, pick):
        return TryOnSlot(slot=pick.slot, private=True)
    return TryOnSlot(slot=pick.slot, pieces=tuple(pick.pieces))


def card_of(view: WardrobeView, ans: Answer) -> TryOnCard:
    """The card for one answer: the primary look only, a private slot covered."""
    picks = ans.suggestion.primary.picks[:MAX_SLOTS]
    return TryOnCard(
        day=ans.day.isoformat(),
        plan=ans.plan.id if ans.plan is not None else None,
        code=ans.code if CODE.fullmatch(ans.code) else "",
        slots=[_slot(view, p) for p in picks if p.pieces],
    )


def show(view: WardrobeView, ans: Answer) -> bool:
    """Put the card beside this reply; False outside a reply, when it is full, or when the look
    can't be carried (then the answer itself is unchanged and a warning is logged)."""
    try:
        card = card_of(view, ans)
    except ValidationError:
        log.warning("tryon card: the look could not be carried on the card")
        return False
    return add_card(card)


def missing(cards: Sequence[object]) -> str:
    """Row 388's check on one reply's cards (its test, the eval and their control): "" when the
    reply carries exactly one try-on card, else what is wrong."""
    found = [c for c in cards if isinstance(c, TryOnCard)]
    if not found:
        return "no try-on card in the reply"
    return "" if len(found) == 1 else "more than one try-on card"


__all__ = ["CODE", "MAX_SLOTS", "card_of", "missing", "show"]
