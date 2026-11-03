# src/jarvis/whatsapp/restore.py
"""WhatsApp draft cards for a conversation opened again (slice 12 final review; Layer 3 → 1).

A reply's cards travel with the reply only (`jarvis.tools.reply_cards`), so a draft's Open in
WhatsApp button used to vanish when the owner reloaded the page. A draft is the owner's own message
to send, not Google's data, so GET /v1/sessions/{id} rebuilds each one from what is stored anyway:
the whatsapp_draft tool result (the number, its source, "assumed India", the text). Every card
goes through `draft.draft_card` again — the number must be E.164, the text clean, the warning set
from the stored source, and the wa.me link is BUILT from the number and text, never read — so a
stored result that no longer checks is skipped, never shown half-right. Maps and YouTube cards are
never rebuilt (Google's terms: JARVIS caches nothing from Google but place ids).

Only a result that answers a `whatsapp_draft` call of the turn just before it counts (tool-use ids
may repeat across turns), only a `draft_ready` one that is not an error, and at most `MAX_DRAFTS`
per reply, as on the live reply. Each card belongs to the next assistant reply with text: the one
the owner saw it under. The stored text is what the model was shown (`tools.external.model_text`
removed what can't be seen), so the rebuilt link is the one for that text.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from jarvis.core.models import Session, StoredDraft
from jarvis.llm.base import ContentBlock, Role, ToolCall, ToolResultBlock
from jarvis.tools.reply_cards import MAX_DRAFTS
from jarvis.whatsapp.draft import WhatsAppCard, draft_card

TOOL = "whatsapp_draft"
MAX_TURNS = 400  # the newest turns of a conversation that are read
# a fenced Contacts name (`tools.external.wrap_external`): its body between the two markers
_FENCED = re.compile(
    r"\A<<EXTERNAL CONTENT from [^\n>]* · ([0-9a-f]{6})>>\n(.*)\n<<END \1>>\Z", re.S
)


def _body(content: str) -> dict[str, Any] | None:
    """The JSON result after the gateway's one-line prefix; None when it doesn't parse."""
    head, sep, body = content.partition("\n")
    if not sep or not head.startswith("[untrusted tool output"):
        return None
    try:
        data = json.loads(body)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _unfenced(name: object) -> str | None:
    """A Contacts name without its fence ('' when it can't be read; None when there is none)."""
    if name is None:
        return None
    m = _FENCED.match(name) if isinstance(name, str) else None
    return m.group(2) if m else ""


def card_of(content: str) -> WhatsAppCard | None:
    """The draft card a stored whatsapp_draft result describes, checked again; else None."""
    data = _body(content)
    if data is None or data.get("status") != "draft_ready" or data.get("sent") is not False:
        return None
    to = data.get("to")
    text = data.get("text")
    if not isinstance(to, dict) or not isinstance(text, str):
        return None
    number, source = to.get("number"), to.get("from")
    if not isinstance(number, str):
        return None
    return draft_card(
        name=_unfenced(to.get("name")),
        number=number,
        text=text,
        source=source if isinstance(source, str) else "elsewhere",
        assumed=to.get("assumed_india") is True,
    )


def _drafts_in(blocks: Sequence[ContentBlock], calls: Mapping[str, str]) -> list[WhatsAppCard]:
    """The draft cards among one turn's results that answer a whatsapp_draft call in `calls`."""
    found: list[WhatsAppCard] = []
    for b in blocks:
        if not isinstance(b, ToolResultBlock) or b.is_error or calls.get(b.tool_use_id) != TOOL:
            continue
        if (card := card_of(b.content)) is not None:
            found.append(card)
    return found


def stored_drafts(session: Session) -> list[StoredDraft]:
    """The conversation's draft cards, rebuilt and checked (see the module docstring)."""
    out: list[StoredDraft] = []
    waiting: list[WhatsAppCard] = []
    calls: dict[str, str] = {}  # the latest turn's tool calls: id -> tool name
    start = max(0, len(session.turns) - MAX_TURNS)
    for i, t in enumerate(session.turns[start:], start=start):
        asked = {b.id: b.name for b in t.blocks if isinstance(b, ToolCall)}
        waiting += _drafts_in(t.blocks, calls)
        calls = asked
        if t.role is Role.ASSISTANT and t.content.strip() and waiting:
            out += [StoredDraft(turn=i, card=c) for c in waiting[:MAX_DRAFTS]]
            waiting = []
    return out


__all__ = ["StoredDraft", "card_of", "stored_drafts"]
