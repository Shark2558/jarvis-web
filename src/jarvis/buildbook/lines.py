# src/jarvis/buildbook/lines.py
"""The build book's fixed lines (R6, docs/plans/r6-build-book.md D13). Pinned word for word by
tests/test_r6_seams.py; never model text, so they work with the AI off.

Placeholders: `{h}` the honorific ("Sir"), `{his}` his / hers / theirs from it, `{by}` "<creator
name>, my owner and creator", or just "my owner and creator" when Book settings has no name.
`say` fills them in ONE pass, so a creator name can never smuggle in another placeholder.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from types import MappingProxyType

from jarvis.buildbook.model import Audience

LINES: Mapping[str, str] = MappingProxyType(
    {
        # asking (D13)
        "ask": "Do you have any questions about how I'm built?",
        "follow_up": "Anything else you'd like to know?",
        # refusals (D12, D13)
        "refuse_data": "That belongs to my owner, and none of it is in this session. "
        "I can tell you how I'm built.",
        "refuse_action": "I can't do anything from the build book; "
        "I can explain how that feature works.",
        "refuse_meta": "I'll keep to explaining how I'm built.",
        "ai_off": "My conversational brain is off, so I can't take questions; "
        "the show still works.",
        "limit": "That's all the questions I can take in one session.",
        # the closing (D13): guest and owner
        "credit": "Everything you've seen was designed and built by {by}. The credit is all {his}.",
        "sealed_guest": "The code is sealed in my vault, for the people my owner allows.",
        "thanks_guest": "Thank you for listening.",
        "sealed_owner": "The code is sealed in your vault, for the people you allow, {h}.",
        "thanks_owner": "Thank you, {h}.",
        # a finished guest session leaves the lock on (D10)
        "hand_back": "Please hand the device back to my owner.",
    }
)
CLOSING: Mapping[Audience, tuple[str, ...]] = MappingProxyType(
    {
        "guest": ("credit", "sealed_guest", "thanks_guest"),
        "owner": ("credit", "sealed_owner", "thanks_owner"),
    }
)
OWNER_AND_CREATOR = "my owner and creator"
_HERS = frozenset({"maam", "madam", "miss", "mrs", "ms", "lady", "madame"})
_PLACEHOLDER = re.compile(r"\{(h|his|by)\}")


def possessive(honorific: str) -> str:
    """`{his}`: his for "Sir"; hers for "Ma'am", "Madam", "Miss", "Mrs", "Ms"; else theirs."""
    word = re.sub(r"[^a-z]", "", honorific.lower())
    if word == "sir":
        return "his"
    return "hers" if word in _HERS else "theirs"


def credited(creator: str) -> str:
    """`{by}`: "<name>, my owner and creator", or "my owner and creator" with no name set."""
    name = " ".join(creator.split())
    return f"{name}, {OWNER_AND_CREATOR}" if name else OWNER_AND_CREATOR


def say(line_id: str, *, honorific: str, creator: str = "") -> str:
    """The fixed line `line_id` with its placeholders filled (KeyError for an unknown id)."""
    values = {"h": honorific, "his": possessive(honorific), "by": credited(creator)}
    return _PLACEHOLDER.sub(lambda m: values[m.group(1)], LINES[line_id])


def closing(audience: Audience, *, honorific: str, creator: str = "") -> tuple[str, ...]:
    """The closing's lines in the order they are spoken."""
    return tuple(say(i, honorific=honorific, creator=creator) for i in CLOSING[audience])


__all__ = ["CLOSING", "LINES", "OWNER_AND_CREATOR", "closing", "credited", "possessive", "say"]
