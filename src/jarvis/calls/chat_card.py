# src/jarvis/calls/chat_card.py
"""The call card under a chat reply (R18 I1; E's `console-calls-card.js` draws `call_card` with
Call, Edit and Cancel; `jarvis.tools.reply_cards`).

When the brain proposes `calls_place` in a chat, A1's look-up (`CallsService.preview`) stores
the card it built as a waiting card and shows it under the reply, so his Call there is the same
press as in the Calls panel (`POST /v1/calls/cards/{id}/approve`, his passkey when asked). The
gateway's own approval card for that proposal stays one way to approve it; whichever he uses,
the stored card is used once (A1 refuses the other). Like every reply card it is never stored
with the conversation, never in what the model sees and never on Telegram (`telegram.format`
draws only its own kinds). The whole number is on it, as on the Calls panel's own card (his own
screen); the console shows its last 4 digits only.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from jarvis.calls.models import CARD_ID, E164, Booking, CallCard, CardLimits, CardStatus


class CallReplyCard(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["call_card"] = "call_card"
    id: str = Field(pattern=CARD_ID)
    status: CardStatus
    number_e164: str = Field(pattern=E164)
    number_masked: str = Field(max_length=24)
    contact_name: str = Field(default="", max_length=80)
    purpose: str = Field(max_length=600)
    may_say: tuple[str, ...] = ()
    may_agree: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    template: str | None = None
    booking: Booking | None = None
    limits: CardLimits = CardLimits()
    estimate_inr: float | None = None
    new_number: bool = False
    needs_passkey: bool = False

    @classmethod
    def of(cls, card: CallCard, masked: str) -> CallReplyCard:
        return cls(
            id=card.id,
            status=card.status,
            number_e164=card.number_e164,
            number_masked=masked,
            contact_name=card.contact_name,
            purpose=card.purpose,
            may_say=card.may_say,
            may_agree=card.may_agree,
            languages=card.languages,
            template=card.template,
            booking=card.booking,
            limits=card.limits,
            estimate_inr=card.estimate_inr,
            new_number=card.new_number,
            needs_passkey=card.new_number,
        )


__all__ = ["CallReplyCard"]
