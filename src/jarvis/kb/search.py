# src/jarvis/kb/search.py
"""Searching the owner's notes: deterministic code, no model call (R2 D10; Layer 3).

BM25 (`recall.retrieval.bm25`) over the words of each live note's title and tags (counted twice),
text, note about the link and saved page excerpt, with recall's tokeniser (lower-case, stop words
out, light stemming, Malayalam / Devanagari marks kept). Two small boosts: the share of query words
found in the title, and an update in the last 30 days. Ties break on the note id, so the answer
never depends on the order the notes came in. At most `MAX_HITS` hits, each with a snippet of at
most `SNIPPET_CHARS` characters cut around the first matching word.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from jarvis.kb.models import MAX_HITS, SNIPPET_CHARS, Note
from jarvis.recall.retrieval import bm25
from jarvis.recall.text import _WORD, tokens  # noqa: PLC2701 - the one word pattern recall uses

RECENT = timedelta(days=30)
TITLE_BOOST = 0.3
RECENT_BOOST = 0.1
HEAD_CHARS = 100  # how much text to show before the matching word
WEIGHT = 2  # title and tags count twice

_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Hit:
    note: Note
    score: float
    snippet: str
    from_page: bool = False  # the snippet is the saved page's text (other people's words)


def _doc(n: Note) -> Counter[str]:
    toks: list[str] = []
    for part in (n.title, *n.tags):
        toks.extend(tokens(part) * WEIGHT)
    for part in (n.text, n.owner_note, n.page.excerpt if n.page else ""):
        toks.extend(tokens(part))
    return Counter(toks)


def _snippet(n: Note, query: set[str]) -> tuple[str, bool]:
    fields = [(n.text, False), (n.owner_note, False), (n.page.excerpt if n.page else "", True)]
    for text, from_page in fields:
        for m in _WORD.finditer(text):
            if set(tokens(m.group(0))) & query:
                start = max(0, m.start() - HEAD_CHARS)
                chunk = _SPACE.sub(" ", text[start : start + SNIPPET_CHARS]).strip()
                return chunk, from_page
    for text, from_page in fields:
        if text:
            return _SPACE.sub(" ", text[:SNIPPET_CHARS]).strip(), from_page
    return n.title[:SNIPPET_CHARS], False


def rank(notes: Iterable[Note], query: str, now: datetime, *, kind: str | None = None) -> list[Hit]:
    """The best matches for `query` among the live notes (of `kind`, when given)."""
    pool = sorted(
        (n for n in notes if n.live and (kind is None or n.kind == kind)), key=lambda n: n.id
    )
    q = set(tokens(query))
    if not pool or not q:
        return []
    scored: list[tuple[float, Note]] = []
    for n, raw in zip(pool, bm25([_doc(n) for n in pool], q), strict=True):
        if raw <= 0:
            continue
        share = len(q & set(tokens(n.title))) / len(q)
        boost = 1 + TITLE_BOOST * share + (RECENT_BOOST if now - n.updated_at <= RECENT else 0)
        scored.append((raw * boost, n))
    scored.sort(key=lambda s: (-s[0], s[1].id))
    hits = []
    for score, n in scored[:MAX_HITS]:
        snippet, from_page = _snippet(n, q)
        hits.append(Hit(n, score, snippet, from_page))
    return hits


__all__ = ["Hit", "rank"]
