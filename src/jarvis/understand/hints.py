# src/jarvis/understand/hints.py
"""Per-turn recognition hints (R11.1; plan D9; Layer 2 input processing). Deterministic: plain
code, no model.

The hint list for a spoken turn is, in this order and at most `voice_hint_words` (40) long:

  1. the names of the files waiting on the composer and attached in this conversation, as they
     would be said: the stem's words ("study-plan.csv" -> "study plan") and the kind ("CSV",
     "Excel", "PowerPoint");
  2. the conversation's own distinctive nouns, newest first: a Capitalised word in the middle of
     one of the OWNER's messages, or a longer word he used more than once. Only his own turns are
     read, never a reply (which may carry a mail's or a web page's words).

They go to the cloud recogniser as speech contexts beside the base list and his own "Words to
recognise" (which keep their own limit and are never crowded out), to the browser recogniser
where it takes hints, and to the fixed rules as what a near-miss may mean. Every hint passes
`voice.settings.clean_phrase` (letters, digits, spaces and - ' . & only, at most 40 characters),
so a hostile file name cannot put anything else into a request. File names are the owner's own
data and go only to his own Google speech project, as the phrase list does; nothing is logged.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Sequence

from jarvis.understand.words import FUNCTION_WORDS, split_words
from jarvis.voice.settings import PHRASE_CHARS, clean_phrase

MAX_FILE_NAMES = 20
MAX_NOUNS = 15
MAX_MESSAGES = 12  # owner turns looked at, newest first
MAX_MESSAGE_CHARS = 2_000
MIN_NOUN = 4
KIND_WORDS: dict[str, str] = {
    "csv": "CSV",
    "xlsx": "Excel",
    "xlsm": "Excel",
    "xls": "Excel",
    "pptx": "PowerPoint",
    "pdf": "PDF",
    "docx": "Word",
    "md": "Markdown",
    "markdown": "Markdown",
    "zip": "zip",
}
_BREAKS = re.compile(r"[\s_\-.]+")
_ALLOWED_PUNCT = frozenset("-'.&")


def _phrase(raw: str) -> str | None:
    """`raw` as one acceptable hint: other characters become spaces, whole words are kept
    while they fit, and the result must pass `clean_phrase`."""
    kept = "".join(
        ch if unicodedata.category(ch)[0] in "LMN" or ch in _ALLOWED_PUNCT else " "
        for ch in unicodedata.normalize("NFC", raw[:400])
    )
    words: list[str] = []
    used = 0
    for word in kept.split():
        if used + len(word) + (1 if words else 0) > PHRASE_CHARS:
            break
        words.append(word)
        used += len(word) + (1 if len(words) > 1 else 0)
    return clean_phrase(" ".join(words)) if words else None


def _dedupe(items: Sequence[str], limit: int) -> tuple[str, ...]:
    seen: dict[str, str] = {}
    for item in items:
        seen.setdefault(item.casefold(), item)
        if len(seen) >= limit:
            break
    return tuple(seen.values())[: max(0, limit)]


def file_hints(names: Sequence[str]) -> tuple[str, ...]:
    """Each file's stem as words, then its kind as it is said."""
    out: list[str] = []
    for name in list(names)[:MAX_FILE_NAMES]:
        base = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
        stem, dot, ext = base.rpartition(".")
        if not dot or not stem:
            stem, ext = base, ""
        said = _phrase(" ".join(_BREAKS.split(stem)))
        if said:
            out.append(said)
        kind = KIND_WORDS.get(ext.lower())
        if kind:
            out.append(kind)
    return _dedupe(out, 2 * MAX_FILE_NAMES)


def _proper(words: list[str], ends: list[bool]) -> list[str]:
    """Words written with a capital in the middle of a sentence (or all in capitals)."""
    out: list[str] = []
    starts = True
    for word, ends_here in zip(words, ends, strict=True):
        shouting = len(word) >= 2 and word.isupper() and word.isalpha()
        titled = len(word) >= 2 and word[0].isupper() and word[1:].islower() and not starts
        if (shouting or titled) and word.casefold() not in FUNCTION_WORDS:
            out.append(word)
        starts = ends_here
    return out


def conversation_nouns(messages: Sequence[str]) -> tuple[str, ...]:
    """The distinctive nouns of the owner's own messages (oldest first in, newest first out)."""
    recent = [m[:MAX_MESSAGE_CHARS] for m in list(messages)[-MAX_MESSAGES:]]
    split = [split_words(m) for m in recent]
    counts = Counter(
        w.key
        for words in split
        for w in words
        if len(w.core) >= MIN_NOUN and w.core.isalpha() and w.key not in FUNCTION_WORDS
    )
    found: list[str] = []
    for words in reversed(split):
        cores = [w.core for w in words]
        found += _proper(cores, [w.ends_sentence for w in words])
        found += [w.core for w in words if counts[w.key] >= 2]
    cleaned = [p for p in (_phrase(w) for w in found) if p]
    return _dedupe(cleaned, MAX_NOUNS)


def turn_hints(
    file_names: Sequence[str], owner_messages: Sequence[str], *, limit: int
) -> tuple[str, ...]:
    """The per-turn hints: files first, then the conversation's nouns, at most `limit`."""
    if limit <= 0:
        return ()
    return _dedupe([*file_hints(file_names), *conversation_nouns(owner_messages)], limit)


__all__ = ["KIND_WORDS", "conversation_nouns", "file_hints", "turn_hints"]
