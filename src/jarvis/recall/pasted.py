# src/jarvis/recall/pasted.py
"""Owner messages that are really someone else's text (slice 8 D4, review finding 6).

Learning reads only the owner's own words. An owner who pastes a mail, a forwarded message or a
long document into the chat is quoting someone else: that message is not learning input. Kept
deliberately simple and conservative — a false "pasted" only means one message is not learned.
"""

from __future__ import annotations

import re

PASTE_CHARS = 1_500
QUOTED_LINES = 3
_HEADER = re.compile(r"(?im)^\s*(?:from|to|cc|bcc|subject|sent|date|reply-to)\s*:\s*\S")
_WROTE = re.compile(r"(?i)\bon\b[^\n]{3,160}\bwrote\s*:")
_FORWARDED = re.compile(
    r"(?im)(?:forwarded message|begin forwarded message|original message|^\s*fwd?\s*:)"
)
_QUOTED = re.compile(r"(?m)^\s*>")


def looks_pasted(text: str) -> bool:
    """Very long, mail headers, "On … wrote:", forwarded markers, or mostly `>`-quoted."""
    if len(text) > PASTE_CHARS:
        return True
    headers = len(_HEADER.findall(text))
    if headers >= 2 or (headers == 1 and "\n" in text.strip()):
        return True
    if _WROTE.search(text) or _FORWARDED.search(text):
        return True
    quoted = len(_QUOTED.findall(text))
    lines = len([ln for ln in text.splitlines() if ln.strip()])
    return quoted >= QUOTED_LINES or (quoted >= 2 and quoted * 2 >= lines)


__all__ = ["PASTE_CHARS", "looks_pasted"]
