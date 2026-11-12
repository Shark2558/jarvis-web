# src/jarvis/picture/queries.py
"""The two word checks of an outward query on a picture turn (R11.1 D21-D; I1 reviews; Layer 4).

Plain code, no model. `jarvis.picture.turnguard` picks one per call:

- **strict** (`untold`): the picture MAY show a person (the look said so, nobody looked at this
  message's picture, it could not be read, or anything failed). The query may carry only words
  the owner typed in this message, words the picture shows (its read text and vetted things),
  and `FREE_WORDS`: small words, ordinary search words and generic thing words, none of which is
  ever part of a name. Every other word is refused, in any script and any letter case, inside a
  link or joined with `_`, and in every query of the turn on its own. So a name split across two
  queries ("Lekha weather", then "Examplekar news") never goes out either.
- **light** (`light_refuses`): the picture is KNOWN to show no person. D's name shapes: a
  person-shaped phrase, a run of two capitalised name words, or a bare name (in any case), now
  read with a mark-aware tokeniser, with a link's parts tested on their own, and with no "one
  word left is a topic" escape when a word that sits beside a person's name is there ("Kohli
  score", "news Lekha").

Strict is light plus `untold`, so it never lets through what light refuses.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from jarvis.picture.words import (
    JOINS,
    NOT_NAME,
    OPENERS,
    PERSON_SEARCH_WORDS,
    QUERY_WORDS,
    THING_WORDS,
    capitalised,
    is_thing_word,
    letter_runs,
    name_shaped,
    person_shaped,
    plain,
    raw_words,
    word_set,
    words_of,
)

# Small words of a question or a search ("how do I", "is it", "more than"): never a name.
_SMALL = frozenset(
    """
    i me my mine we us you your it its is are was were be being been am do does did done can
    could should would shall might must much many more less most least than then so
    very too also only just not no yes any per about into onto off up down out over under get
    got make made use used need want like give take go going come there here which who whom
    whose what when where why how whats hows
    """.split()
)
# Search words D's lighter check leaves out of QUERY_WORDS because each could be a surname on its
# own ("Price", "Best"): in strict mode a name needs a word that is NOT free, so they may be free.
_STRICT_SEARCH = frozenset("price prices priced pricing best".split())
# Strict mode's own words, beside his and the picture's: none of them is ever part of a name.
FREE_WORDS = (
    NOT_NAME | OPENERS | JOINS | QUERY_WORDS | PERSON_SEARCH_WORDS | THING_WORDS | _SMALL
) | _STRICT_SEARCH
_LINK = re.compile(r"[/:]")
_LINK_PARTS = re.compile(r"[/:?#&=]+")
_IN_A_PART = re.compile(r"[._\-]+")


def _free(word: str) -> bool:
    return word in FREE_WORDS or is_thing_word(word)


def untold(query: str, own: Iterable[str]) -> list[str]:
    """The words of `query` (cut at `_`, `-`, `.`, `/`, `'`: a link or a joined name is words
    like any other) that are neither in `own` (what he typed, what the picture shows) nor free.
    A single letter is an initial and names nobody by itself."""
    known = frozenset(letter_runs(" ".join(own)))
    return [w for w in letter_runs(query) if len(w) > 1 and w not in known and not _free(w)]


def _name_part(word: str, first: bool) -> bool:
    """Could this capitalised word be part of a person's name? Not a small word, not an
    ordinary search word, and not the query's sentence-case opener ("Weather Mumbai")."""
    p = plain(word)
    return p not in NOT_NAME and p not in QUERY_WORDS and not (first and p in OPENERS)


def named_by_capitals(words: list[str], known: frozenset[str]) -> bool:
    """A run of two or more capitalised words (ALL CAPS too) that could be a person's name
    ("Lekha Examplekar", "MEENU EXAMPLEWALA", "R K Examplekar"), one of them neither typed by him
    nor shown by the picture. A lone capitalised word is a place or a brand as often as a name
    ("weather in Mumbai"), and is let through like the query's opening capital always was
    (R11.1 I1, the over-caution check)."""
    i = 0
    while i < len(words):
        if not capitalised(words[i]):
            i += 1
            continue
        j = i
        while j < len(words) and capitalised(words[j]):
            j += 1
        run = [plain(w) for k, w in enumerate(words[i:j]) if _name_part(w, i + k == 0)]
        if len(run) >= 2 and any(w not in known for w in run):
            return True
        i = j
    return False


def bare_name(words: list[str], known: frozenset[str]) -> bool:
    """The words are a person's name and little else, in any letter case or script ("lekha
    examplekar", "Kohli", "rajesh examplekar contact number", "लेखा एक्झाम्पलकर"): once the
    ordinary search words are set aside, what is left is shaped like a name and he neither typed
    nor was shown any of it. One word left beside ordinary search words is a topic ("monsoon
    weather forecast"), unless a word that sits beside a person's name is there ("Kohli score",
    "Modi news today", "news Lekha": I1 reviews, security M3 and code M3)."""
    rest = [w for w in words if plain(w) not in QUERY_WORDS]
    if not rest or word_set(rest) & known:
        return False
    beside_a_person = any(plain(w) in PERSON_SEARCH_WORDS for w in words)
    if len(rest) < len(words) and len(rest) < 2 and not beside_a_person:
        return False
    if any(p.endswith("es") and is_thing_word(p[:-2]) for p in map(plain, rest)):
        return False  # "festival dishes", "match boxes": a thing, its plural in -es
    return name_shaped(" ".join(rest))


def link_parts(query: str) -> list[list[str]]:
    """The words of each part of a link or `site:` word that joins two words or more with `_`,
    `.` or `-` ("…/wiki/Lekha_Examplekar", "instagram.com/lekha.examplekar"), each part on its own,
    so a name inside a link is tested like a name typed out."""
    out: list[list[str]] = []
    for token in query.split():
        if not _LINK.search(token):
            continue
        for part in _LINK_PARTS.split(token):
            words = raw_words(_IN_A_PART.sub(" ", part))
            if len(words) >= 2:
                out.append(words)
    return out


def light_refuses(query: str, known: frozenset[str]) -> bool:
    """D's name shapes over the query and over each part of a link in it."""
    if person_shaped(query) and not set(words_of(query)) <= known:
        return True  # "who is the woman in red", "actress with short hair"
    whole = raw_words(query)
    if named_by_capitals(whole, known) or bare_name(whole, known):
        return True  # "Lekha Examplekar minister", "LEKHA EXAMPLEKAR", a bare name
    return any(named_by_capitals(p, known) or bare_name(p, known) for p in link_parts(query))


__all__ = [
    "FREE_WORDS",
    "bare_name",
    "light_refuses",
    "link_parts",
    "named_by_capitals",
    "untold",
]
