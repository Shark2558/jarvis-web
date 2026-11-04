# src/jarvis/telegram/format.py
"""A chat reply as Telegram messages (R1 D5): plain text (no parse_mode), split at 4,096
characters, at most 3 messages, then "...the rest is in the console". Cards become a line each:
WhatsApp draft -> "Open in WhatsApp: <link>", Maps -> name + Google Maps link, YouTube -> title +
link. Links come from the validated cards, never from the model's words."""

from __future__ import annotations

import re

from jarvis.core.models import ChatResponse
from jarvis.tools.reply_cards import PlacesCard, RouteCard, VideosCard
from jarvis.whatsapp.draft import WhatsAppCard

LIMIT = 4096
MAX_MESSAGES = 3
OFFLINE_PREFIX = "(Offline — answered by your laptop)"
MORE = "\n…the rest is in the console"
EMPTY = "(no reply)"
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def card_lines(cards: list[object]) -> list[str]:
    out: list[str] = []
    for c in cards:
        if isinstance(c, WhatsAppCard):
            who = c.name or c.number
            out.append(f"Draft for {who}: {c.text}\nOpen in WhatsApp: {c.link}")
        elif isinstance(c, PlacesCard):
            out += [f"{p.name}" + (f" - {p.address}" if p.address else "") + f"\n{p.url}"
                    for p in c.items[:5]]  # fmt: skip
        elif isinstance(c, RouteCard):
            out.append(f"{c.origin} to {c.destination} ({c.duration_minutes} min)\n{c.url}")
        elif isinstance(c, VideosCard):
            out += [f"{v.title}\nhttps://www.youtube.com/watch?v={v.id}" for v in c.items[:5]]
    return out


def _cut(text: str) -> tuple[str, str]:
    """(a piece of at most LIMIT characters, the rest), cut at a paragraph, line or space."""
    if len(text) <= LIMIT:
        return text, ""
    window = text[:LIMIT]
    for sep in ("\n\n", "\n", " "):
        i = window.rfind(sep)
        if i > LIMIT // 2:
            return window[:i].rstrip(), text[i:].lstrip()
    return window, text[LIMIT:]


def split_text(text: str) -> list[str]:
    """At most MAX_MESSAGES messages; when more would be needed the last ends with MORE."""
    parts: list[str] = []
    rest = text
    while rest and len(parts) < MAX_MESSAGES:
        piece, rest = _cut(rest)
        parts.append(piece)
    if rest:
        last = parts[-1]
        parts[-1] = last[: LIMIT - len(MORE)].rstrip() + MORE
    return parts or [EMPTY]


def reply_messages(resp: ChatResponse) -> list[str]:
    blocks = [_CONTROL.sub("", resp.reply).strip()]
    blocks += card_lines(list(resp.cards))
    text = "\n\n".join(b for b in blocks if b) or EMPTY
    if resp.offline:
        text = f"{OFFLINE_PREFIX} {text}"
    return split_text(text)


__all__ = [
    "EMPTY",
    "LIMIT",
    "MAX_MESSAGES",
    "MORE",
    "OFFLINE_PREFIX",
    "reply_messages",
    "split_text",
]
