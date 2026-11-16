# src/jarvis/wardrobe/catalog/search.py
"""Finding a piece by his words (docs/plans/r13-wardrobe.md D6, D7; INV-01, 09, 13, 15).

Deterministic and explainable; no model. The query's words split into:
- type words ("belt", "shoes", "t-shirt", "kurta" ...): only pieces of those types;
- colour and pattern words from the fixed lists ("light blue", "striped"): a piece whose colour or
  pattern says otherwise is left out; a match he confirmed (locked) counts twice a suggestion;
- one of his places ("in drawer 2"): only pieces kept there;
- everything else: BM25 (`recall.retrieval.bm25`) over his labels, with the Things key
  (`belongings.text.thing_key`: case, plurals and "my" / "the" do not matter).
`best` is the one top match, or None when two tie (two black belts: told apart by place or
label, INV-15) or nothing matches ("Not in your wardrobe": Things' turn, D6).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from jarvis.belongings.text import thing_key
from jarvis.recall.retrieval import bm25
from jarvis.wardrobe.catalog.store import CatalogStore
from jarvis.wardrobe.model import CATEGORIES, COLOURS, PATTERNS, TYPES, Piece, WardrobeView

MAX_MATCHES = 20
_STOP = frozenset(
    {"where", "is", "are", "my", "the", "a", "an", "in", "on", "at", "find", "what", "which"}
    | {"of", "and", "kept", "put", "i", "did", "do", "have", "how", "many", "me", "show", "pair"}
)
_EXTRA_TYPES: Mapping[str, tuple[str, ...]] = {
    "shoe": ("dress_shoe", "sneaker", "boot"), "t shirt": ("t_shirt",), "tee": ("t_shirt",),
    "tshirt": ("t_shirt",), "jean": ("jeans",), "trouser": ("trousers",), "pant": ("trousers",),
    "chino": ("chinos",), "short": ("shorts",), "jogger": ("joggers",), "slipper": ("slipper",),
    "chappal": ("sandal", "slipper"), "underwear": ("underpants", "briefs", "boxers"),
    "spectacle": ("eyewear",), "glass": ("eyewear",), "jewelry": ("jewellery",),
}  # fmt: skip
_EXTRA_PATTERNS: Mapping[str, str] = {
    "stripe": "striped", "check": "checked", "checkered": "checked", "print": "printed",
    "dot": "dotted", "polka": "dotted", "plain": "solid",
}  # fmt: skip


def _vocabulary() -> dict[str, tuple[str, ...]]:
    words: dict[str, tuple[str, ...]] = {}
    for types in TYPES.values():
        for t in types:
            words[thing_key(t.replace("_", " "))] = (t,)
    return {**words, **{thing_key(k): v for k, v in _EXTRA_TYPES.items()}}


TYPE_WORDS = _vocabulary()
COLOUR_WORDS = {thing_key(c.replace("_", " ")): c for c in COLOURS} | {"gray": "grey"}
PATTERN_WORDS = {thing_key(p): p for p in PATTERNS} | {
    thing_key(k): v for k, v in _EXTRA_PATTERNS.items()
}


def count_word(word: object) -> str | None:
    """A type or a category for `wardrobe_count` ("shirts" -> shirt, "shoes" -> footwear)."""
    key = thing_key(word)
    for c in CATEGORIES:
        if key in (c, thing_key(c)):
            return c
    types = TYPE_WORDS.get(key, ())
    if len(types) == 1:
        return types[0]
    cats = {c for c, ts in TYPES.items() for t in types if t in ts}
    return cats.pop() if len(cats) == 1 else None


@dataclass(frozen=True)
class Found:
    best: Piece | None
    matches: tuple[Piece, ...]


@dataclass(frozen=True)
class _Query:
    types: frozenset[str]
    colours: frozenset[str]
    patterns: frozenset[str]
    place: str | None
    rest: frozenset[str]


def _take(words: list[str], table: Mapping[str, object]) -> list[object]:
    """Longest phrases first ("light blue" before "blue"); the words found are removed."""
    found: list[object] = []
    for size in (3, 2, 1):
        i = 0
        while i + size <= len(words):
            key = " ".join(words[i : i + size])
            if key in table:
                found.append(table[key])
                del words[i : i + size]
            else:
                i += 1
    return found


def parse(view: WardrobeView, query: str) -> _Query:
    key = thing_key(query)
    place = None
    for p in sorted(view.places.values(), key=lambda x: -len(x.label)):
        pk = thing_key(p.label)
        if pk and f" {pk} " in f" {key} ":
            place, key = p.id, f" {key} ".replace(f" {pk} ", " ", 1).strip()
            break
    words = [w for w in key.split() if w not in _STOP]
    types = {t for found in _take(words, TYPE_WORDS) for t in found}  # type: ignore[attr-defined]
    colours = {str(c) for c in _take(words, COLOUR_WORDS)}
    patterns = {str(p) for p in _take(words, PATTERN_WORDS)}
    return _Query(
        frozenset(types), frozenset(colours), frozenset(patterns), place, frozenset(words)
    )


def _fit(p: Piece, wanted: frozenset[str], field: str, *values: str | None) -> float | None:
    """None: the piece says otherwise; else its score (a locked match counts twice)."""
    if not wanted:
        return 0.0
    have = {v for v in values if v}
    if not have:
        return 0.0
    if not have & wanted:
        return None
    return 2.0 if field in p.locked else 1.0


def _label_bag(p: Piece) -> Counter[str]:
    return Counter(thing_key(p.label).split())


def rank(view: WardrobeView, query: str, pieces: Iterable[Piece] | None = None) -> Found:
    q = parse(view, query)
    pool = [p for p in (pieces if pieces is not None else view.active())]
    pool = [p for p in pool if (not q.types or p.type in q.types)]
    pool = [p for p in pool if q.place is None or p.place == q.place]
    scored: list[tuple[float, Piece]] = []
    bags = bm25([_label_bag(p) for p in pool], set(q.rest))
    for p, text in zip(pool, bags, strict=True):
        colour = _fit(p, q.colours, "colour", p.colour, p.second)
        pattern = _fit(p, q.patterns, "pattern", p.pattern)
        if colour is None or pattern is None:
            continue
        if not (q.types or q.colours or q.patterns or q.place or text):
            continue
        scored.append((colour + pattern + text, p))
    scored.sort(key=lambda sp: (-sp[0], sp[1].id))
    matches = tuple(p for _, p in scored[:MAX_MATCHES])
    unique = len(scored) == 1 or (len(scored) > 1 and scored[0][0] > scored[1][0])
    return Found(matches[0] if matches and unique else None, matches)


class Search:
    def __init__(self, store: CatalogStore) -> None:
        self.store = store

    async def find(self, uid: str, query: str) -> Found:
        return rank(await self.store.view(uid), query)


__all__ = [
    "COLOUR_WORDS",
    "MAX_MATCHES",
    "PATTERN_WORDS",
    "TYPE_WORDS",
    "Found",
    "Search",
    "count_word",
    "rank",
]
