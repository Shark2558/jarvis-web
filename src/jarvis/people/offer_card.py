# src/jarvis/people/offer_card.py
"""The "Look up" reply card (R11.1 D21-D; security review H1, M2): only the card's checked shape,
so `jarvis.tools.reply_cards` can list it without importing anything that imports it back. The
offer itself (when it is made, its fixed words) is `jarvis.people.offer`; the console draws it with
`JarvisPeople.offerCard` (console-people.js), text only.
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

KIND: Final = "people_offer"
BUTTON: Final = "Look up"
CAPTION_MAX = 200


class PeopleOfferCard(BaseModel):
    """A name the picture's own text holds, the caption line it was read from, the fixed words
    and ONE button. Checked when made: a name shaped like a name, the fixed button, bounded text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["people_offer"] = "people_offer"
    name: str = Field(min_length=1, max_length=80)
    caption: str = Field(min_length=1, max_length=CAPTION_MAX)
    words: str = Field(min_length=1, max_length=300)
    button: Literal["Look up"] = "Look up"

    @field_validator("name")
    @classmethod
    def _a_name(cls, v: str) -> str:
        # read when a card is made: reply_cards lists this module, and the word shapes import
        # (through core.models) reply_cards itself, so importing them here at load would loop
        from jarvis.picture.words import name_shaped

        if not name_shaped(v):
            raise ValueError("not shaped like a name")
        return v


__all__ = ["BUTTON", "CAPTION_MAX", "KIND", "PeopleOfferCard"]
