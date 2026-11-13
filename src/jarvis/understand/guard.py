# src/jarvis/understand/guard.py
"""Plain code has the last word on the fast tier's reading (R11.1; plan D8 step 2, D21-B; code
review M1).

`acceptable(heard, understood, reading=..., ...)` is True only when the model's sentence

  1. keeps every guarded word of the heard sentence, exactly and in order: numbers and anything
     with a digit (amounts, dates, times, phone numbers), number / money / time / date words,
     e-mail addresses, people's names (`words.levels`, HARD and SOFT);
  2. brings no new number, amount, date, time or address, and no name that was not heard;
  3. keeps every ACTION word (`words.ACTION_WORDS`: open, read, send, pay, delete, ...) of the
     fixed rules' reading exactly, in order: none changed, none added, none dropped;
  4. changes a word only into a near spelling of it (`near.sounds_like`, the near-match
     distance), or into what the recogniser itself offered in that very place (an
     alternative, aligned word for word); drops or adds only small function words;
  5. uses only words that were heard, offered as an alternative, are a hint, are written by a
     fixed rule, or are small function words;
  6. is still the same request: about as long, mostly the same words in the same order.

The baseline for 3, 4 and 6 is the fixed rules' own reading (`reading`; the heard words when
none is given): their corrections are plain code and already trusted. Anything else is thrown
away and JARVIS asks its one question.

What this guarantees: the fast tier can only respell misheard words, so it can never change
which action is taken, add one, or touch a number, an amount, a date, a time, a name, a phone
number or an e-mail address. A hint (a file name, which an outsider may have chosen) is never
enough on its own for a change: it can at most decide between near spellings of a heard word
(which file "the buget sheet" is) or cause a question. Every spoken write still goes through
its approval card on the voice channel.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from difflib import SequenceMatcher

from jarvis.understand.near import sounds_like
from jarvis.understand.rules import RULES
from jarvis.understand.words import (
    ACTION_WORDS,
    FUNCTION_WORDS,
    fixed_words,
    guarded_words,
    protected_words,
    split_words,
)

MAX_CHARS = 2_000
MIN_SIMILAR = 0.6  # of the reading's words, in order
MAX_LONGER = 3  # words the reading may add or drop
RULE_WORDS: frozenset[str] = frozenset(
    word.casefold() for rule in RULES for word in rule.means.split()
)


def _in_order(need: Sequence[str], have: Sequence[str]) -> bool:
    it = iter(have)
    return all(any(word == other for other in it) for word in need)


def _keys(text: str) -> list[str]:
    return [w.key for w in split_words(text)]


def _actions(keys: Sequence[str]) -> list[str]:
    return [k for k in keys if k in ACTION_WORDS]


def _content(keys: Sequence[str]) -> list[str]:
    return [k for k in keys if k not in FUNCTION_WORDS]


def _aligned(base: list[str], other: list[str], i1: int, i2: int) -> list[str]:
    """The words of `other` that stand where `base[i1:i2]` stands (word-for-word alignment)."""
    out: list[str] = []
    for tag, a1, a2, b1, b2 in SequenceMatcher(None, base, other, autojunk=False).get_opcodes():
        lo, hi = max(a1, i1), min(a2, i2)
        if tag == "equal" and lo < hi:
            out += other[b1 + lo - a1 : b1 + hi - a1]
        elif tag != "equal" and (lo < hi or (a1 == a2 and i1 <= a1 <= i2)):
            out += other[b1:b2]
    return out


def _sounds_alike(base: list[str], new: list[str], offered: list[list[str]]) -> bool:
    """Rule 4: each changed run of real words is a near spelling, or what an alternative says
    in that place; only function words may come or go on their own."""
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, base, new, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        gone, came = _content(base[i1:i2]), _content(new[j1:j2])
        if not gone and not came:
            continue  # "the" added or dropped
        if not gone or not came:
            return False  # a real word dropped, or one brought in without replacing any
        if sounds_like(" ".join(gone), " ".join(came)):
            continue
        if any(_content(_aligned(base, alt, i1, i2)) == came for alt in offered):
            continue
        return False
    return True


def acceptable(
    heard: str,
    understood: str,
    *,
    reading: str | None = None,
    alternatives: Sequence[str] = (),
    hints: Sequence[str] = (),
) -> bool:
    """May the model's `understood` stand for `heard`? (See the module docstring.)"""
    if not understood.strip() or len(understood) > MAX_CHARS or "\n" in understood.strip():
        return False
    hint_tuple = tuple(hints)
    said = [w.core for w in split_words(understood)]
    if not _in_order(guarded_words(heard, hint_tuple), said):
        return False  # 1. a protected word is gone or changed
    if Counter(fixed_words(understood)) - Counter(fixed_words(heard)):
        return False  # 2. a new number, amount, date, time or address
    heard_words = {w.core for w in split_words(heard)}
    if any(name not in heard_words for name in protected_words(understood, hint_tuple)):
        return False  # 2. a name that was not heard
    base, new = _keys(reading or heard), _keys(understood)
    if _actions(base) != _actions(new):
        return False  # 3. an action changed, added or dropped
    offered = [_keys(a) for a in alternatives]
    if not _sounds_alike(base, new, offered):
        return False  # 4. a word that is not a respelling of the one it replaces
    allowed = {*_keys(heard), *base, *RULE_WORDS, *FUNCTION_WORDS}
    for extra in (*alternatives, *hint_tuple):
        allowed.update(_keys(extra))
    if any(key not in allowed for key in new):
        return False  # 5. a word from nowhere
    if abs(len(new) - len(base)) > MAX_LONGER:
        return False
    return SequenceMatcher(None, base, new).ratio() >= MIN_SIMILAR  # 6.


__all__ = ["RULE_WORDS", "acceptable"]
