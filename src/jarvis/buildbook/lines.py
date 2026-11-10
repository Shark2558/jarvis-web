# src/jarvis/buildbook/lines.py
"""D13's fixed lines (R6, docs/plans/r6-build-book.md), pinned word for word by
tests/test_r6_buildbook_model.py. Every refusal and the closing are these exact strings: the
talk-through's guards (D12) answer with them and make NO model call, the show speaks them (scenes
12 and 13; POST /v1/book/show/speak takes a key of `LINES` as its line id, besides a beat id).

Placeholders, filled by `render` only: `{h}` the honorific (Settings.user_honorific), `{his}` the
possessive that goes with it (`possessive`), `{by}` the creator credit (`credit_by`: "<name>, my
owner and creator" or just "my owner and creator" when Book settings has no name). Text is
inserted literally; a name holding braces is never read as a placeholder.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal

LINES: Mapping[str, str] = MappingProxyType(
    {
        # the talk-through (D11, D12)
        "ask": "Do you have any questions about how I'm built?",
        "anything_else": "Anything else you'd like to know?",
        "refuse_data": "That belongs to my owner, and none of it is in this session. "
        "I can tell you how I'm built.",
        "refuse_action": "I can't do anything from the build book; "
        "I can explain how that feature works.",
        "refuse_meta": "I'll keep to explaining how I'm built.",
        "ai_off": "My conversational brain is off, so I can't take questions; "
        "the show still works.",
        "limit": "That's all the questions I can take in one session.",
        # the closing (D13, D14): guest and owner
        "credit": "Everything you've seen was designed and built by {by}. The credit is all {his}.",
        "sealed_guest": "The code is sealed in my vault, for the people my owner allows.",
        "thanks_guest": "Thank you for listening.",
        "sealed_owner": "The code is sealed in your vault, for the people you allow, {h}.",
        "thanks_owner": "Thank you, {h}.",
        # a finished guest session leaves the lock on (D10)
        "hand_back": "Please hand the device back to my owner.",
    }
)
CLOSING: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "guest": ("credit", "sealed_guest", "thanks_guest"),
        "owner": ("credit", "sealed_owner", "thanks_owner"),
    }
)
OWNER_AND_CREATOR = "my owner and creator"
CREATOR_MAX = 40  # D16: the creator name in Book settings
_HERS = frozenset({"ma'am", "madam", "maam", "miss", "mrs", "ms", "lady", "madame"})


def possessive(honorific: str) -> str:
    """'his' for Sir, 'hers' for Ma'am / Madam and the like, else 'theirs'."""
    word = honorific.strip().lower().rstrip(".")
    if word == "sir":
        return "his"
    return "hers" if word in _HERS else "theirs"


def credit_by(creator_name: str | None) -> str:
    """D13's `{by}`: the creator's name (whitespace folded, at most 40 characters) + ", my owner
    and creator", or just "my owner and creator" when no name is set."""
    name = " ".join((creator_name or "").split())[:CREATOR_MAX].strip()
    return f"{name}, {OWNER_AND_CREATOR}" if name else OWNER_AND_CREATOR


def render(line_id: str, *, h: str, his: str, by: str) -> str:
    """One fixed line with its placeholders filled. KeyError for a line that isn't D13's."""
    text = LINES[line_id]
    out: list[str] = []
    values = {"{h}": h, "{his}": his, "{by}": by}
    i = 0
    while i < len(text):
        hit = next((k for k in values if text.startswith(k, i)), None)
        if hit is None:
            out.append(text[i])
            i += 1
        else:
            out.append(values[hit])
            i += len(hit)
    return "".join(out)


def closing(audience: Literal["owner", "guest"], *, h: str, his: str, by: str) -> tuple[str, ...]:
    """The closing lines in the order they are spoken (D13)."""
    return tuple(render(line, h=h, his=his, by=by) for line in CLOSING[audience])


__all__ = [
    "CLOSING",
    "CREATOR_MAX",
    "LINES",
    "OWNER_AND_CREATOR",
    "closing",
    "credit_by",
    "possessive",
    "render",
]
