# src/jarvis/buildbook/writer/search.py
"""R6.4 D4 (docs/plans/r6-4-book-look.md): search over one release's compiled pages for
`GET /v1/book/pages/search?q=` (`api/book_pages.py`). No AI, no index service, ₹0.

- `normal_query(q)`: trimmed, its spaces folded; None unless 2 to 60 characters (the route's 422).
- `corpus(f, flows)`: each page's searchable words, built once per sealed release
  (`writer/serve.BookPages` keeps it with the release's files): its title; its "headings", the
  flowchart's title and box labels (every page shares the five section headings, so they would
  match everything); and its text, the five sections as compiled (facts filled, backticks taken
  out), never "Where in the code".
- `find(corpus, release, q)`: every query word (at most `WORDS_MAX`) must match the start of a word
  of the page, case-blind (casefold), or for a word of 5 letters or more the start of its light
  stem ("expiry" -> "expir": expires, expired). Ranked by the words found in the title, then in
  the headings, then by the hits in the text, then the index's order: at most `RESULTS_MAX`
  results and the `total` that matched. Each result's snippet is about `SNIPPET` characters of the
  text around its first hit ("…" where it is cut; the page's opening words when only its title or
  headings matched), and `marks` are the matched words as [start, end) ranges in UTF-16 code
  units, as JavaScript's `String.slice` counts them. Plain text only: the reader draws the marks.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from jarvis.buildbook.writer.http import SearchHit, SearchView
from jarvis.buildbook.writer.model import DRAFT_SECTIONS, Page, PagesFile

QUERY_MIN, QUERY_MAX = 2, 60
WORDS_MAX, RESULTS_MAX, MARKS_MAX = 8, 20, 20
SNIPPET, LEAD = 160, 60  # characters shown; how many before the first hit
STEMS = ("ies", "ing", "ied", "es", "ed", "s", "y", "e")
STEM_FROM, STEM_KEEP = 5, 4  # a word this long is stemmed; a stem keeps at least this many
HITS_COUNTED = 50
CUT = "…"
_WORD = re.compile(r"\w+")
_SPACE = re.compile(r"\s+")
Span = tuple[int, int, str]  # start, end, the word casefolded


@dataclass(frozen=True)
class Doc:
    order: int
    page: Page
    title: tuple[str, ...]
    heads: tuple[str, ...]
    text: str
    spans: tuple[Span, ...]


def normal_query(q: str) -> str | None:
    folded = _SPACE.sub(" ", unicodedata.normalize("NFC", q)).strip()
    return folded if QUERY_MIN <= len(folded) <= QUERY_MAX else None


def _words(text: str) -> tuple[str, ...]:
    return tuple(w.casefold() for w in _WORD.findall(text))


def _stem(word: str) -> str:
    if len(word) < STEM_FROM:
        return word
    for suffix in STEMS:
        if word.endswith(suffix) and len(word) - len(suffix) >= STEM_KEEP:
            return word[: -len(suffix)]
    return word


def _plain(page: Page) -> str:
    parts = [s.text for s in page.sections if s.id in DRAFT_SECTIONS and s.text.strip()]
    return _SPACE.sub(" ", " ".join(parts).replace("`", "")).strip()


def _heads(flow: Mapping[str, Any] | None) -> tuple[str, ...]:
    if not isinstance(flow, Mapping):
        return ()
    labels = [str(n.get("label", "")) for n in flow.get("nodes", ()) if isinstance(n, Mapping)]
    return _words(" ".join([str(flow.get("title", "")), *labels]))


def corpus(f: PagesFile, flows: Mapping[str, Any]) -> tuple[Doc, ...]:
    out = []
    for order, page in enumerate(f.pages):
        text = _plain(page)
        spans = tuple((m.start(), m.end(), m.group().casefold()) for m in _WORD.finditer(text))
        out.append(Doc(order, page, _words(page.title), _heads(flows.get(page.id)), text, spans))
    return tuple(out)


# ---- matching and ranking ---------------------------------------------------------------------
def _matcher(words: Sequence[str]) -> tuple[tuple[str, ...], ...]:
    """Each query word's accepted prefixes: itself, and its stem when it has one."""
    return tuple(tuple(dict.fromkeys((w, _stem(w)))) for w in words)


def _hits(prefixes: tuple[str, ...], token: str) -> bool:
    return any(token.startswith(p) for p in prefixes)


def _score(doc: Doc, wanted: tuple[tuple[str, ...], ...]) -> tuple[int, int, int] | None:
    title = heads = text = 0
    for prefixes in wanted:
        in_title = any(_hits(prefixes, t) for t in doc.title)
        in_heads = any(_hits(prefixes, t) for t in doc.heads)
        in_text = sum(_hits(prefixes, s[2]) for s in doc.spans)
        if not (in_title or in_heads or in_text):
            return None
        title, heads, text = title + in_title, heads + in_heads, text + in_text
    return title, heads, min(text, HITS_COUNTED)


# ---- the snippet --------------------------------------------------------------------------------
def _u16(text: str, index: int) -> int:
    return len(text[:index].encode("utf-16-le")) // 2


def _window(text: str, at: int) -> tuple[int, int]:
    start = max(0, at - LEAD)
    if start > 0:
        space = text.find(" ", start, at)
        start = space + 1 if space != -1 else start
    end = min(len(text), start + SNIPPET)
    if end < len(text):
        space = text.rfind(" ", start, end)
        end = space if space > at else end
    return start, end


Marks = tuple[tuple[int, int], ...]


def _snippet(doc: Doc, wanted: tuple[tuple[str, ...], ...]) -> tuple[str, Marks]:
    matched = [s for s in doc.spans if any(_hits(p, s[2]) for p in wanted)]
    start, end = _window(doc.text, matched[0][0] if matched else 0)
    head = CUT if start > 0 else ""
    snippet = head + doc.text[start:end] + (CUT if end < len(doc.text) else "")
    marks: list[tuple[int, int]] = []
    for s, e, _ in matched:
        if start <= s and e <= end and len(marks) < MARKS_MAX:
            a, b = len(head) + s - start, len(head) + e - start
            marks.append((_u16(snippet, a), _u16(snippet, b)))
    return snippet, tuple(marks)


def find(docs: Sequence[Doc], release: str, q: str) -> SearchView:
    """The search's answer (`q` already `normal_query`'d)."""
    words = tuple(dict.fromkeys(_words(q)))[:WORDS_MAX]
    wanted = _matcher(words)
    scored = [(score, doc) for doc in docs if words and (score := _score(doc, wanted))]
    scored.sort(key=lambda p: (-p[0][0], -p[0][1], -p[0][2], p[1].order))
    results = []
    for _, doc in scored[:RESULTS_MAX]:
        snippet, marks = _snippet(doc, wanted)
        results.append(SearchHit(id=doc.page.id, title=doc.page.title, kind=doc.page.kind,
                                 snippet=snippet, marks=marks))  # fmt: skip
    return SearchView(release=release, q=q, results=tuple(results), total=len(scored))


__all__ = [
    "QUERY_MAX",
    "QUERY_MIN",
    "RESULTS_MAX",
    "SNIPPET",
    "WORDS_MAX",
    "Doc",
    "corpus",
    "find",
    "normal_query",
]
