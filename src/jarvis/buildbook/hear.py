# src/jarvis/buildbook/hear.py
"""A spoken question in the build book's show (R6.2 Part 1; Phase A findings 4.4-4.5; Layer 2
input processing): the book's own words for the recogniser, the console's free "heard /
understood as" rules on what came back, and the plain words each failure is said in.

    vocabulary(book)        public names only: a fixed list (the stack, the outside services by
                            name) plus this release's stack and service labels; cleaned as the
                            owner's "Words to recognise" are, unique, at most MAX_VOCABULARY
    understood(heard, hints) `jarvis.understand.rules.apply` (R11.1): known Indian-English
                            mishearings and close matches against `hints`. No model call (Rs 0,
                            guest-safe): an unsure reading keeps the sure words only
    words(reason, owner=)   one plain sentence a reason; the owner alone gets a short pointer to
                            Vitals. A guest never sees setup or admin text: no Cloud Shell
                            command, no setting name, no "Vitals", no rupees

`api/book_show.py` passes the vocabulary to the recogniser for both audiences and corrects
against it, plus the owner's own words for an OWNER session only (R6 D1).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

from jarvis.buildbook.model import Book
from jarvis.buildbook.ports import BookSource
from jarvis.logging import get_logger
from jarvis.understand.rules import apply
from jarvis.voice.settings import clean_phrase

log = get_logger(__name__)

MAX_VOCABULARY: Final = 60
BOOK_WORDS: Final[tuple[str, ...]] = (
    "JARVIS",
    "build book",
    "Firestore",
    "Cloud Run",
    "Google Cloud",
    "FastAPI",
    "Pydantic",
    "passkey",
    "passkeys",
    "WebAuthn",
    "Claude",
    "Anthropic",
    "Gemini",
    "Sonnet",
    "Haiku",
    "Opus",
    "brain router",
    "gateway",
    "vault",
    "keyring",
    "Vitals",
    "Speech-to-Text",
    "Text-to-Speech",
    "Tailscale",
    "Home Assistant",
    "Frigate",
    "Mosquitto",
    "MQTT",
    "Telegram",
    "WhatsApp",
    "Gmail",
    "Google Calendar",
    "Google Drive",
    "three.js",
    "Playwright",
    "GitHub Actions",
    "Docker",
    "Redis",
    "Android",
)
_PUBLIC_STACK_ROLES: Final = frozenset({"language", "vendored", "3d"})
_SPLIT: Final = re.compile(r"\s*(?:,|/|\(|\)|\band\b)\s*")

# ---- the words a failure is said in --------------------------------------------------------------
_WORDS: Final[dict[str, str]] = {
    "not_configured": (
        "Listening isn't set up on this server, so JARVIS can't hear spoken questions here. "
        "Type your question."
    ),
    "api_disabled": (
        "The speech service is switched off for this JARVIS, so it can't listen right now. "
        "Type your question."
    ),
    "upstream_error": (
        "The speech service isn't answering right now. Try again in a moment, or type your "
        "question."
    ),
    "timeout": "The speech service took too long to answer. Try again, or type your question.",
    "busy": (
        "The speech service is busy right now. Try again in a few seconds, or type your question."
    ),
    "session_budget": "This session's spoken questions are used up. Type your question.",
    "budget_reached": (
        "This month's free listening minutes are used up and the monthly spending limit is "
        "reached, so JARVIS can't listen now. Type your question."
    ),
    "budget_unreadable": (
        "JARVIS can't check this month's spending right now, so it isn't listening. Type your "
        "question."
    ),
    "rejected": (
        "The speech service couldn't take that recording. Try again, or type your question."
    ),
}
_OWNER_TAIL: Final[dict[str, str]] = {
    "not_configured": " Vitals shows what cloud listening needs.",
    "api_disabled": " Vitals shows how to switch it on.",
    "budget_reached": " You can raise the limit in Vitals.",
}
REASONS: Final[tuple[str, ...]] = tuple(_WORDS)
SPEAK_OFF: Final = "Use the browser's voice."  # narration: the page reads the line itself


def words(reason: str, *, owner: bool) -> str:
    """The sentence for `reason` (an unknown one: the speech service isn't answering)."""
    base = _WORDS.get(reason, _WORDS["upstream_error"])
    return base + (_OWNER_TAIL.get(reason, "") if owner else "")


# ---- the book's own words for the recogniser -----------------------------------------------------
def _pieces(names: Iterable[str]) -> Iterable[str]:
    for name in names:
        yield from (p for p in _SPLIT.split(name) if p)


def _unique(names: Iterable[str], limit: int) -> tuple[str, ...]:
    seen: dict[str, str] = {}
    for raw in names:
        word = clean_phrase(raw)
        if word is None or len(word) < 2:
            continue
        seen.setdefault(word.casefold(), word)
        if len(seen) >= limit:
            break
    return tuple(seen.values())


def vocabulary(book: Book | None) -> tuple[str, ...]:
    """Public names for a spoken question: the fixed list, then this release's stack and
    service names."""
    found: list[str] = []
    if book is not None:
        found.extend(i.name for i in book.stack.items if i.role in _PUBLIC_STACK_ROLES)
        found.extend(_pieces(s.label for s in book.integrations.services))
    return _unique((*BOOK_WORDS, *found), MAX_VOCABULARY)


class BookWords:
    """`vocabulary` of the release `source` serves, read once a release (`BookService.words`). A
    book that can't be read gives the fixed list alone, and is asked again next time."""

    def __init__(self, source: BookSource) -> None:
        self._source = source
        self._have: tuple[str, tuple[str, ...]] | None = None  # (release id, words)

    def __call__(self) -> tuple[str, ...]:
        rel = self._source.current()
        rid = rel.id if rel is not None and rel.ok else ""
        if self._have is not None and self._have[0] == rid:
            return self._have[1]
        book = self._read() if rid else None
        found = vocabulary(book)
        if book is not None or not rid:
            self._have = (rid, found)
        return found

    def _read(self) -> Book | None:
        try:
            return self._source.book()
        except Exception as exc:  # noqa: BLE001 - the fixed words still help
            log.warning("build book unreadable for its words", extra={"error": type(exc).__name__})
            return None


# ---- heard / understood as -----------------------------------------------------------------------
@dataclass(frozen=True)
class Understood:
    text: str  # the sure reading, for the question box
    heard: str  # what the recogniser said
    changed: bool


def understood(heard: str, hints: Sequence[str]) -> Understood:
    """The console's fixed R11.1 rules on one transcript; never a model call."""
    said = " ".join(heard.split())
    if not said:
        return Understood(text="", heard="", changed=False)
    out = apply(said, tuple(hints))
    return Understood(text=out.text, heard=said, changed=out.changed)


__all__ = [
    "BOOK_WORDS",
    "BookWords",
    "MAX_VOCABULARY",
    "REASONS",
    "SPEAK_OFF",
    "Understood",
    "understood",
    "vocabulary",
    "words",
]
