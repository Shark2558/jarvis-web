# src/jarvis/people/offer.py
"""The "Look up" offer of a name the picture's text holds (R11.1 D21-D; security review H1, M2,
M3; Layer 6 -> 1).

When the main brain asks `research_person` for a name on a picture turn and the owner did not
type it, but the conversation's last picture research read it off the picture's own text, nothing
is researched: the tool's result is these fixed words and a reply card with one button, "Look
up". Only his press of it starts the people research (in the People panel, behind the unchanged
check). The card shows the very caption line the name was read from, so he sees where it came
from (a caption the look invented is still only an offer, and the check still decides).

`PeopleOfferCard` is checked when made (a name shaped like a name, the fixed button, bounded
text). It is shown through `jarvis.tools.reply_cards.add_card` once that module lists the kind
(I1 adds it to `AnyCard`; until then `show` says no and the result says the button is missing).
The console draws it with `JarvisPeople.offerCard` (console-people.js), text only.
"""

from __future__ import annotations

import typing
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from jarvis.picture.turnguard import Offer
from jarvis.picture.words import name_shaped
from jarvis.tools import reply_cards
from jarvis.tools.external import wrap_external

KIND: Final = "people_offer"
BUTTON: Final = "Look up"
CAPTION_MAX = 200
FROM_TEXT = "text in the picture"
NOTE = (
    "Nothing was researched. Tell the owner these words and quote the caption line; the owner "
    "presses 'Look up' on the card under your reply to research the name."
)
NOT_SHOWN = (
    "Nothing was researched, and the 'Look up' button could not be shown with this reply. Tell "
    "the owner these words and quote the caption line; to research the name, the owner types it."
)


class PeopleOfferCard(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["people_offer"] = "people_offer"
    name: str = Field(min_length=1, max_length=80)
    caption: str = Field(min_length=1, max_length=CAPTION_MAX)
    words: str = Field(min_length=1, max_length=300)
    button: Literal["Look up"] = "Look up"

    @field_validator("name")
    @classmethod
    def _a_name(cls, v: str) -> str:
        if not name_shaped(v):
            raise ValueError("not shaped like a name")
        return v


def kind_known() -> bool:
    """Does the reply carry this kind of card yet (`reply_cards.AnyCard` lists it)?"""
    return PeopleOfferCard in typing.get_args(reply_cards.AnyCard)


def show(card: PeopleOfferCard) -> bool:
    """Show the card under this reply. False outside a reply, when the reply is full, or before
    the card kind is registered."""
    return kind_known() and reply_cards.add_card(card)  # type: ignore[arg-type]


def offered(offer: Offer) -> dict[str, Any]:
    """The tool's result for an offer: fixed words, the caption fenced, nothing researched."""
    words = offer.words()
    shown = show(PeopleOfferCard(name=offer.name, caption=offer.caption[:CAPTION_MAX], words=words))
    return {
        "offer": True,
        "refused": False,
        "message": words,
        "spoken": words,
        "caption": wrap_external(offer.caption, source=FROM_TEXT),
        "card_shown": shown,
        "note": NOTE if shown else NOT_SHOWN,
    }


__all__ = ["BUTTON", "KIND", "NOT_SHOWN", "PeopleOfferCard", "kind_known", "offered", "show"]
