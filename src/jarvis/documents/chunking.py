# src/jarvis/documents/chunking.py
"""Chunks of an attached document's text, and finding them again (slice 10 E).

A chunk is ≈ 4,000 characters of plain text, measured in what the gateway really sends: tool
results are JSON with ASCII escapes, so a Malayalam letter costs six characters (`\\u0d15`) and an
emoji twelve. Measuring the JSON cost keeps every `doc_read` part (two chunks) and every
`doc_search` answer under the gateway's 12,000-character cut for any script. Chunks break at a
blank line, else a line end, a sentence end or a space in the last 40 %. Ranking is the memory
ranking (BM25 over the same tokens, `jarvis.recall`), so documents and notes are found alike.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from jarvis.documents.models import CHUNK_COST, MAX_CHUNKS
from jarvis.recall.retrieval import bm25
from jarvis.recall.text import tokenize

_SEPARATORS = ("\n\n", "\n", ". ", " ")
_KEEP_SHARE = 0.6  # never cut a chunk shorter than 60 % of what would fit
_PROBE = re.compile(r"\w{3,}")
_ESCAPED_2 = frozenset('"\\\b\f\n\r\t')
_ASCII_COST = tuple(2 if chr(o) in _ESCAPED_2 else 6 if o < 0x20 else 1 for o in range(128))


@dataclass(frozen=True)
class Chunk:
    text: str
    start: int  # offset in the document's text
    page: int | None = None  # PDF: the page the chunk starts on
    page_end: int | None = None  # PDF: the page it ends on


def _cost(ch: str) -> int:
    o = ord(ch)
    if o < 128:
        return _ASCII_COST[o]
    return 12 if o > 0xFFFF else 6


def json_cost(text: str) -> int:
    """len(json.dumps(text)) - 2: what `text` costs inside a tool result."""
    return sum(_cost(ch) for ch in text)


def _end_within(text: str, pos: int, budget: int) -> int:
    used = 0
    j = pos
    n = len(text)
    while j < n:
        c = _cost(text[j])
        if used + c > budget:
            break
        used += c
        j += 1
    return j


def fit(text: str, budget: int) -> str:
    """The longest start of `text` whose JSON cost is within `budget`."""
    return text[: _end_within(text, 0, budget)]


def _cut_point(text: str, pos: int, end: int) -> int:
    window = text[pos:end]
    floor = int(len(window) * _KEEP_SHARE)
    for sep in _SEPARATORS:
        k = window.rfind(sep, floor)
        if k != -1:
            return pos + k + len(sep)
    return end


def _page_at(starts: Sequence[int], offset: int) -> int | None:
    return bisect_right(starts, offset) if starts else None


def split(
    text: str, page_starts: Sequence[int] = (), *, cost: int = CHUNK_COST
) -> tuple[list[Chunk], bool]:
    """The chunks of `text` and whether the chunk cap cut it short."""
    chunks: list[Chunk] = []
    pos = 0
    n = len(text)
    while pos < n:
        if len(chunks) == MAX_CHUNKS:
            return chunks, True
        end = _end_within(text, pos, cost)
        if end < n:
            end = _cut_point(text, pos, end)
        piece = text[pos:end]
        if piece.strip():
            chunks.append(
                Chunk(piece, pos, _page_at(page_starts, pos), _page_at(page_starts, end - 1))
            )
        pos = end
    return chunks, False


def pages_label(first: int | None, last: int | None) -> str | None:
    if first is None:
        return None
    if last is None or last == first:
        return f"p. {first}"
    return f"pp. {first}–{last}"


def rank(texts: Sequence[str], query: str) -> list[tuple[int, float]]:
    """(index, score) of every text that shares a word with `query`, best first."""
    q = set(tokenize(query))
    if not q:
        return []
    scored = bm25([Counter(tokenize(t)) for t in texts], q)
    return sorted(((i, s) for i, s in enumerate(scored) if s > 0), key=lambda x: (-x[1], x[0]))


def _probes(query: str) -> list[str]:
    out: list[str] = []
    for w in _PROBE.findall(query.lower()):
        out.append(w)
        if len(w) > 5:
            out.append(w[: max(5, len(w) - 3)])  # "penalties" also finds "penalty"
    return out


def excerpt(text: str, query: str, budget: int) -> str:
    """A window of `text` around the first place the query's words appear, within `budget`."""
    if json_cost(text) <= budget:
        return text
    low = text.lower()
    found = [i for i in (low.find(p) for p in _probes(query)) if i >= 0]
    at = min(found, default=0)
    start = max(0, at - budget // 4)
    space = text.rfind(" ", 0, start)
    if start and space != -1 and start - space < 40:
        start = space + 1
    lead = "… " if start else ""
    piece = fit(text[start:], budget - json_cost(lead) - 2)
    tail = " …" if start + len(piece) < len(text) else ""
    return lead + piece + tail


__all__ = ["Chunk", "excerpt", "fit", "json_cost", "pages_label", "rank", "split"]
