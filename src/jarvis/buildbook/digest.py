# src/jarvis/buildbook/digest.py
"""Which parts of the book's digest go into a question's context (R6 D11). Deterministic: a
keyword score (how often the question's words, folded and lightly stemmed, occur in a chunk, plus
a bonus when a word names the chunk's section), highest first and then by id; when nothing scores,
the chunks in their own order. Chunks are taken while their fenced size fits the budget (D2:
each chunk is at most 1,500 characters, so a 10,000-character context holds about six)."""

from __future__ import annotations

import re
from collections import Counter

from jarvis.buildbook.guard import normalise
from jarvis.buildbook.model import Digest, DigestChunk
from jarvis.buildbook.prompt import fenced_len

SECTION_BONUS = 3
_WORD = re.compile(r"[^\W_]+")
STOP = frozenset(
    "the and for are but not you your yours with what when where which who whom how why does do "
    "did can could would should will about into from that this these those there their them they "
    "his her him she was were has have had been being its it's jarvis tell me please explain "
    "work works working use used using get got make made way ways like just also than then".split()
)


def _stem(word: str) -> str:
    for suffix in ("ing", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def terms(question: str) -> frozenset[str]:
    """The question's content words (3+ letters, no stop words), folded and stemmed."""
    words = _WORD.findall(normalise(question))
    return frozenset(_stem(w) for w in words if len(w) >= 3 and w not in STOP)


def score(chunk: DigestChunk, wanted: frozenset[str]) -> int:
    if not wanted:
        return 0
    counts = Counter(_stem(w) for w in _WORD.findall(normalise(chunk.text)))
    hits = sum(counts[t] for t in wanted)
    return hits + (SECTION_BONUS if _stem(chunk.section.lower()) in wanted else 0)


def select(d: Digest, question: str, *, budget: int) -> tuple[DigestChunk, ...]:
    wanted = terms(question)
    scored = [(score(c, wanted), c) for c in d.chunks]
    if any(s > 0 for s, _ in scored):
        ranked = [c for s, c in sorted(scored, key=lambda x: (-x[0], x[1].id)) if s > 0]
    else:
        ranked = sorted(d.chunks, key=lambda c: c.id)
    chosen: list[DigestChunk] = []
    used = 0
    for chunk in ranked:
        size = fenced_len(chunk.id, chunk.text)
        if used + size > budget:
            break
        chosen.append(chunk)
        used += size
    return tuple(chosen)


__all__ = ["SECTION_BONUS", "STOP", "score", "select", "terms"]
