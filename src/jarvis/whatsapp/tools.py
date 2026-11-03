# src/jarvis/whatsapp/tools.py
"""whatsapp_draft (slice 12 D6; Layer 5 Communication): JARVIS writes, the owner taps Send.

`to` is a phone number (digits or E.164; +91 for the owner's 10-digit Indian numbers) or a
contact's name looked up in Google Contacts: one contact with one number is used; several
contacts or several numbers come back as a list and the model asks the owner which one (no
draft). `text` ≤ 2,000 characters (`whatsapp.draft`). The result is a draft — the reply's card
shows the name and number, the text and Open in WhatsApp (a wa.me link the owner clicks) — and
nothing is sent: JARVIS calls no WhatsApp service at all. A number that did not come from the
owner's own words or a Contacts match carries a warning line (`whatsapp.provenance`).

R1 (nothing leaves JARVIS), with its own permission row ("WhatsApp drafts"). A name look-up
reads Contacts, so it also obeys the Contacts row: the look-up names `contacts_search`
(`Preview.also`) and the gateway applies that row's whole decision — Never refuses, Ask first
makes a card (review S1).

Trust (final review): a ready draft to a number the owner TYPED (`number_source` "you": a text
turn's words) vouches for its result (`may_vouch`): it holds only the owner's number and the
text the model wrote, so a second draft or a reminder later in the same message is not turned
into a card by the first draft. A result with a Contacts name (fenced: people write their own
names), a choice list, a number from anywhere else, or a run whose text may carry other people's
words (`ToolContext.outside`: an approved card proposed in a round that read a mail or a page,
as the calendar, reminder and to-do writes mark it) never vouches and taints the round.

Cards (final review, code review CR-1): at most `reply_cards.MAX_DRAFTS` drafts per reply. When
the reply is full the call is refused before anything runs (no Contacts look-up) and answered
{status: "not_shown", sent: false, message} — no link, no `next` — asking the owner to ask again:
never "tap Open in WhatsApp" without a card.

Review S3: what the owner hands to WhatsApp can carry other people's influence — a mail or a page
read this round may have steered the text (2,000 characters of stolen data) and the recipient. So
on a spoken turn or in a tainted round the draft asks first (`ask_when`, honoured for read-only
calls): a one-by-one R1 card (no passkey, never in Approve all) that shows the WHOLE text, line
by line ("> "), with its line count. Security review SEC-1: each quoted line is EXACTLY the text
that is sent (the same string the wa.me link carries; `text_arg` already left only what can be
seen). Review S5: a number written without a country code says "Assumed India (+91)" on both
cards (`to.assumed_india`).
"""

from __future__ import annotations

from typing import Any, Literal

from jarvis.contacts.client import Contact, ContactsClient, ContactsNotGranted, Found
from jarvis.contacts.phones import india_assumed, to_e164
from jarvis.contacts.tools import fenced
from jarvis.core.guardrails import ActionRisk
from jarvis.logging import get_logger
from jarvis.tools.base import Preview, Tool
from jarvis.tools.card import has_invisible_chars, has_line_breaking_chars, one_line
from jarvis.tools.context import require_tool_context
from jarvis.tools.provenance import vouch
from jarvis.tools.reply_cards import DRAFT_NOT_SHOWN, add_card, reply_full, showing_cards
from jarvis.tools.taint import spoken_in_context, tainted_round
from jarvis.whatsapp.draft import (
    ASSUMED_INDIA,
    TEXT_MAX,
    WARNING,
    draft_card,
    text_arg,
    wa_link,
)
from jarvis.whatsapp.provenance import country_typed, number_source

log = get_logger(__name__)
TOOL = "whatsapp_draft"
LOOKUP_TOOL = "contacts_search"  # a name look-up obeys the Contacts permission row too
TO_LIMIT = 100
NUMBERISH_DIGITS = 5  # a `to` with this many digits is a number (and must read as one)
LINK_SHOWN_MAX = 3000  # longer links (a long Malayalam text) are left to the card
QUOTE = "> "  # each line of the text on the approval card: it can't pass for the card's own lines

READY = "Nothing was sent. Tell the owner: it's ready — tap Open in WhatsApp, then Send."
CHOOSE = (
    "Several contacts or numbers match. Ask the owner which one, then call whatsapp_draft again "
    "with that number."
)
MORE = (
    "More contacts match than are shown. Ask the owner for the full name or the number; never "
    "guess."
)
NOT_FOUND = "No contact by that name has a phone number. Ask the owner for the number."
NEED_GRANT = (
    "To find a number by name JARVIS needs Contacts: ask the owner for the number, or to press "
    "Grant next to 'Contacts' in Integrations."
)
NEED_NUMBER = "JARVIS can't look up names here (Google isn't linked). Ask the owner for the number."

Recipient = tuple[Literal["number", "name"], str]


def recipient_arg(value: Any) -> Recipient:
    """('number', E.164) or ('name', one clean line), or ValueError in plain words."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("to is required: a phone number or a contact's name")
    if has_invisible_chars(value) or has_line_breaking_chars(value):
        raise ValueError("to must be a phone number or a contact's name, without hidden characters")
    text = one_line(value, TO_LIMIT + 1)
    if len(text) > TO_LIMIT:
        raise ValueError(f"to is too long (at most {TO_LIMIT} characters)")
    if sum(ch.isdigit() for ch in text) >= NUMBERISH_DIGITS:
        return "number", to_e164(text)  # ValueError: not a phone number JARVIS can use
    if not any(ch.isalpha() for ch in text):
        raise ValueError("to must be a phone number or a contact's name")
    return "name", text


def _check(a: dict[str, Any]) -> None:
    recipient_arg(a.get("to"))
    text_arg(a.get("text"))


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word}" if n == 1 else f"{n:,} {word}s"


def _card_text(a: dict[str, Any]) -> str:
    """The approval card: the recipient, and the WHOLE text — every line quoted, so a line of the
    text can't pass for the card's own "To:" — with its line and character count (review S3).
    Built from the arguments only, so it reads the same when the card is approved."""
    kind, who = recipient_arg(a.get("to"))
    if kind == "name":
        shown = f"{who} (looked up in Contacts)"
    else:
        shown = f"{who} — {ASSUMED_INDIA}" if india_assumed(a.get("to")) else who
    text = text_arg(a.get("text"))
    lines = text.split("\n")
    # SEC-1: each line EXACTLY as it is sent — no one_line, which would collapse or strip what
    # the card then wouldn't show; `text_arg` already left only what can be seen (and the joiners
    # and selectors a script or an emoji needs)
    quoted = [QUOTE + ln if ln else QUOTE.rstrip() for ln in lines]
    count = f"{_plural(len(lines), 'line')}, {_plural(len(text), 'character')}"
    return "\n".join(
        [
            "Write a WhatsApp draft (JARVIS sends nothing; you press Send in WhatsApp)",
            f"To: {shown}",
            f"Text ({count}), in full:",
            *quoted,
        ]
    )


def _asks(a: dict[str, Any]) -> bool:
    """`ask_when`: a spoken turn or a round that read other people's words (review S3)."""
    return tainted_round() or spoken_in_context()


def _options(found: Found) -> list[tuple[Contact, str]]:
    return [(c, p) for c in found.contacts for p in c.phones]


def _choices(found: Found) -> dict[str, Any]:
    matches = [
        {"name": fenced(c.name), "phones": list(c.phones)} for c in found.contacts if c.phones
    ]
    message = f"{CHOOSE} {MORE}" if found.more else CHOOSE
    return {
        "status": "choose_recipient",
        "message": message,
        "matches": matches,
        "more": found.more,
    }


class WhatsAppDrafts:
    def __init__(self, contacts: ContactsClient | None) -> None:
        self.contacts = contacts

    async def draft(self, a: dict[str, Any]) -> Any:
        ctx = require_tool_context()
        uid, outside = ctx.user_id, ctx.outside
        text = text_arg(a.get("text"))
        kind, who = recipient_arg(a.get("to"))
        if reply_full(drafts=True):  # refused before anything runs: no Contacts look-up
            return _not_shown()
        if kind == "number":
            source = number_source(who)
            assumed = _assumed(a.get("to"), who, source)
            return _ready(None, who, text, source, assumed, outside=outside)
        found = await self._look_up(uid, who)
        if isinstance(found, dict):
            return found
        options = _options(found)
        if not options:
            return {"status": "not_found", "message": NOT_FOUND}
        if len(options) > 1 or found.more:  # review C3: more exist than shown — never guess
            return _choices(found)
        contact, number = options[0]
        return _ready(contact.name, number, text, "contacts", False, outside=outside)

    async def _look_up(self, uid: str, name: str) -> Found | dict[str, Any]:
        if self.contacts is None:
            return {"status": "need_number", "message": NEED_NUMBER}
        try:
            await self.contacts.require(uid)
        except ContactsNotGranted:
            return {"status": "permission_needed", "message": NEED_GRANT}
        return await self.contacts.search(uid, name)

    async def preview(self, a: dict[str, Any]) -> Preview:
        """No I/O: the card text, and — for a name — the Contacts row it also obeys."""
        kind, _ = recipient_arg(a.get("to"))
        return Preview(_card_text(a), also=LOOKUP_TOOL if kind == "name" else None)


def _assumed(raw: Any, number: str, source: str) -> bool:
    """India assumed (review S5): the `to` given has no country code, or the owner's own words
    wrote this number only without one (the model may have added the +91 itself)."""
    if not number.startswith("+91"):
        return False
    return india_assumed(raw) or (source == "you" and not country_typed(number))


def _not_shown() -> Any:
    """The reply already shows MAX_DRAFTS drafts: nothing made, nothing sent (our own words)."""
    return vouch({"status": "not_shown", "sent": False, "message": DRAFT_NOT_SHOWN}, True)


def _ready(
    name: str | None, number: str, text: str, source: str, assumed: bool, *, outside: bool
) -> Any:
    """The result the model sees — and, beside it, the owner's draft card for this reply
    (`reply_cards.add_card`: kind "whatsapp", number and text checked again, link rebuilt).
    Vouched only for a number the owner typed, no Contacts name, and a text no outside content
    can have shaped (`outside`; see the module docstring)."""
    card = draft_card(name=name, number=number, text=text, source=source, assumed=assumed)
    if card is None:  # can't happen for checked arguments; the owner can ask again
        log.warning("whatsapp draft card not made", extra={"tool": TOOL})
    elif not add_card(card) and showing_cards():  # within the reply's MAX_DRAFTS, or said so
        return _not_shown()
    link = wa_link(number, text)
    to = {"number": number, "name": fenced(name) if name else None, "from": source}
    out: dict[str, Any] = {
        "status": "draft_ready",
        "sent": False,
        "to": {**to, "assumed_india": assumed},
        "text": text,
        # how long the text the card carries is: `jarvis.whatsapp.restore` rebuilds the card on
        # reload only when the stored text (what the model saw) still has exactly this many
        "characters": len(text),
        "link": link if len(link) <= LINK_SHOWN_MAX else "(long: the owner's card has the button)",
        "next": READY,
    }
    if source not in ("you", "contacts"):
        out["warning"] = WARNING
    if assumed:
        out["country"] = f"{ASSUMED_INDIA}: no country code was given. If it isn't Indian, ask."
    return vouch(out, name is None and source == "you" and not outside)


def whatsapp_tools(contacts: ContactsClient | None) -> list[Tool]:
    """`contacts`: the owner's Contacts (None without a Google link: numbers only)."""
    api = WhatsAppDrafts(contacts)
    return [
        Tool(
            TOOL,
            "Prepare a WhatsApp message for the owner to send. JARVIS never sends it: the owner "
            "gets a card with Open in WhatsApp and presses Send there. `to` is a phone number "
            "(with country code unless Indian; a number without one is read as Indian, so if it "
            "may not be, ask the owner for the country code) or a contact's name (looked up in "
            f"Contacts; if several match, ask the owner which). `text` at most {TEXT_MAX:,} "
            "characters.",
            {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Phone number or contact name"},
                    "text": {"type": "string", "description": "The message, as it will be sent"},
                },
                "required": ["to", "text"],
            },
            ActionRisk.READ_ONLY,
            api.draft,
            agent="whatsapp",
            check=_check,
            summarize=_card_text,
            preview=api.preview,
            ask_when=_asks,
            may_vouch=True,  # only a draft to a number the owner typed (see `_ready`)
        )
    ]


__all__ = ["TOOL", "WhatsAppDrafts", "recipient_arg", "whatsapp_tools"]
