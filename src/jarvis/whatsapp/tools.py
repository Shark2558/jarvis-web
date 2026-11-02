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
(`Preview.also`) and Never there is total. Not `may_vouch`: a contact's name is fenced.
"""

from __future__ import annotations

from typing import Any, Literal

from jarvis.contacts.client import Contact, ContactsClient, ContactsNotGranted, Found
from jarvis.contacts.phones import to_e164
from jarvis.contacts.tools import fenced
from jarvis.core.guardrails import ActionRisk
from jarvis.tools.base import Preview, Tool
from jarvis.tools.card import has_invisible_chars, has_line_breaking_chars, one_line
from jarvis.tools.context import require_tool_context
from jarvis.whatsapp.draft import TEXT_MAX, WARNING, text_arg, wa_link
from jarvis.whatsapp.provenance import number_source

TOOL = "whatsapp_draft"
LOOKUP_TOOL = "contacts_search"  # a name look-up obeys the Contacts permission row too
TO_LIMIT = 100
NUMBERISH_DIGITS = 5  # a `to` with this many digits is a number (and must read as one)
LINK_SHOWN_MAX = 3000  # longer links (a long Malayalam text) are left to the card
CARD_TEXT_LIMIT = 200

READY = "Nothing was sent. Tell the owner: it's ready — tap Open in WhatsApp, then Send."
CHOOSE = (
    "Several contacts or numbers match. Ask the owner which one, then call whatsapp_draft again "
    "with that number."
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


def _card_text(a: dict[str, Any]) -> str:
    kind, who = recipient_arg(a.get("to"))
    shown = who if kind == "number" else f"{who} (looked up in Contacts)"
    return "\n".join(
        [
            "Write a WhatsApp draft (JARVIS sends nothing; you press Send in WhatsApp)",
            f"To: {shown}",
            f"Text: {one_line(text_arg(a.get('text')), CARD_TEXT_LIMIT)}",
        ]
    )


def _options(found: Found) -> list[tuple[Contact, str]]:
    return [(c, p) for c in found.contacts for p in c.phones]


def _choices(found: Found) -> dict[str, Any]:
    matches = [
        {"name": fenced(c.name), "phones": list(c.phones)} for c in found.contacts if c.phones
    ]
    return {"status": "choose_recipient", "message": CHOOSE, "matches": matches, "more": found.more}


class WhatsAppDrafts:
    def __init__(self, contacts: ContactsClient | None) -> None:
        self.contacts = contacts

    async def draft(self, a: dict[str, Any]) -> Any:
        uid = require_tool_context().user_id
        text = text_arg(a.get("text"))
        kind, who = recipient_arg(a.get("to"))
        if kind == "number":
            return _ready(None, who, text, number_source(who))
        found = await self._look_up(uid, who)
        if isinstance(found, dict):
            return found
        options = _options(found)
        if not options:
            return {"status": "not_found", "message": NOT_FOUND}
        if len(options) > 1:
            return _choices(found)
        contact, number = options[0]
        return _ready(contact.name, number, text, "contacts")

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


def _ready(name: str | None, number: str, text: str, source: str) -> dict[str, Any]:
    link = wa_link(number, text)
    out: dict[str, Any] = {
        "status": "draft_ready",
        "sent": False,
        "to": {"number": number, "name": fenced(name) if name else None, "from": source},
        "text": text,
        "link": link if len(link) <= LINK_SHOWN_MAX else "(long: the owner's card has the button)",
        "next": READY,
    }
    if source not in ("you", "contacts"):
        out["warning"] = WARNING
    return out


def whatsapp_tools(contacts: ContactsClient | None) -> list[Tool]:
    """`contacts`: the owner's Contacts (None without a Google link: numbers only)."""
    api = WhatsAppDrafts(contacts)
    return [
        Tool(
            TOOL,
            "Prepare a WhatsApp message for the owner to send. JARVIS never sends it: the owner "
            "gets a card with Open in WhatsApp and presses Send there. `to` is a phone number "
            "(with country code unless Indian) or a contact's name (looked up in Contacts; if "
            f"several match, ask the owner which). `text` at most {TEXT_MAX:,} characters.",
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
        )
    ]


__all__ = ["TOOL", "WhatsAppDrafts", "recipient_arg", "whatsapp_tools"]
