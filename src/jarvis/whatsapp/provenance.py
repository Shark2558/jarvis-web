# src/jarvis/whatsapp/provenance.py
"""Where did a WhatsApp recipient's number come from? (slice 12 D6; Layer 4)

The slice 11 D7 a idea ("un-typed recipient", `tools.gmail` + `tools.addresses`) for phone
numbers: a number is the owner's when it is written in the owner's own words — any owner message
of this conversation (its `content`: never an attached file's text, never JARVIS's words, never a
tool result), or the current message (`taint.owner_text`) — normalised exactly like a recipient
(`contacts.phones.typed_numbers`). It is from Contacts when a Contacts look-up in this
conversation showed it: a `contacts_search` result, or a `whatsapp_draft` choice list (both list
`matches[].phones`). Anything else — a number only in a mail, a page, a document, an event, or
nowhere at all (the model's own) — is from elsewhere, and the draft card shows a warning line.

The Brain opens `conversation_words(session)` around each gateway call (and around an approved
card being carried out), like `web.ledger.web_conversation`. Outside one, only the current
message counts: an unknown conversation can't vouch for a number (fail safe: a warning).
Results are matched to their calls by tool-use id, so text in a mail can't pass for a Contacts
result; a result whose call is not a look-up, an error, or one that does not parse adds nothing.
"""

from __future__ import annotations

import contextvars
import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Literal

from jarvis.contacts.phones import is_e164, typed_numbers
from jarvis.llm.base import ToolCall, ToolResultBlock
from jarvis.tools.taint import owner_text
from jarvis.web.ledger import is_owner_message

if TYPE_CHECKING:
    from jarvis.core.models import Session

Source = Literal["you", "contacts", "elsewhere"]
LOOKUP_TOOLS = frozenset({"contacts_search", "whatsapp_draft"})
MAX_TURNS = 200  # the newest turns of a conversation that are read
MAX_LISTED = 30  # numbers read from one look-up result

_session: contextvars.ContextVar[Session | None] = contextvars.ContextVar(
    "jarvis_whatsapp_conversation", default=None
)


@contextmanager
def conversation_words(session: Session) -> Iterator[None]:
    """Make `session` visible to `number_source` for the duration (always reset)."""
    token = _session.set(session)
    try:
        yield
    finally:
        _session.reset(token)


def _owner_texts(session: Session | None) -> list[str]:
    said = owner_text()
    texts = [said] if said else []
    if session is not None:
        texts += [t.content for t in session.turns[-MAX_TURNS:] if is_owner_message(t)]
    return texts


def _listed(content: str) -> set[str]:
    """`matches[].phones` of one stored look-up result (`GatewayResult.for_model` text)."""
    _, _, body = content.partition("\n")
    try:
        data: Any = json.loads(body)
    except ValueError:
        return set()
    matches = data.get("matches") if isinstance(data, dict) else None
    out: set[str] = set()
    for m in matches if isinstance(matches, list) else []:
        phones = m.get("phones") if isinstance(m, dict) else None
        for p in (phones if isinstance(phones, list) else [])[:MAX_LISTED]:
            if is_e164(p):
                out.add(p)
    return out


def _contact_numbers(session: Session | None) -> set[str]:
    """Numbers the look-ups of this conversation listed. A result pairs only with the calls of
    the turn just before it (ids may repeat across turns: never matched conversation-wide)."""
    if session is None:
        return set()
    found: set[str] = set()
    calls: dict[str, str] = {}  # the latest turn's tool calls: id -> tool name
    for t in session.turns[-MAX_TURNS:]:
        asked = {b.id: b.name for b in t.blocks if isinstance(b, ToolCall)}
        if asked:
            calls = asked
            continue
        for b in t.blocks:
            if not isinstance(b, ToolResultBlock) or b.is_error:
                continue
            if calls.get(b.tool_use_id) in LOOKUP_TOOLS:
                found |= _listed(b.content)
        calls = {}
    return found


def number_source(number: str) -> Source:
    """'you', 'contacts' or 'elsewhere' for an E.164 number (see the module docstring)."""
    session = _session.get()
    if any(number in typed_numbers(text) for text in _owner_texts(session)):
        return "you"
    if number in _contact_numbers(session):
        return "contacts"
    return "elsewhere"


__all__ = ["LOOKUP_TOOLS", "Source", "conversation_words", "number_source"]
