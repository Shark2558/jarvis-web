# src/jarvis/understand/guard.py
"""Plain code has the last word on the fast tier's reading (R11.1; plan D8 step 2, D21-B).

`acceptable(heard, understood, ...)` is True only when the model's sentence

  1. keeps every guarded word of the heard sentence, exactly and in order: numbers and anything
     with a digit (amounts, dates, times, phone numbers), number / money / time / date words,
     e-mail addresses, people's names (`words.levels`, HARD and SOFT);
  2. brings no new number, amount, date, time or address, and no name that was not heard;
  3. uses only words that were heard, that the recogniser offered as an alternative, that are a
     hint (a file name, the conversation's nouns, the owner's own words), that a fixed rule
     writes, or small function words;
  4. is still the same request: about as long, mostly the same words in the same order.

Anything else is thrown away and JARVIS asks its one question. So a hostile file name, an odd
alternative or a model that rambles can at most cause a question; it cannot change what is done.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from difflib import SequenceMatcher

from jarvis.understand.rules import RULES
from jarvis.understand.words import (
    FUNCTION_WORDS,
    fixed_words,
    guarded_words,
    protected_words,
    split_words,
)

MAX_CHARS = 2_000
MIN_SIMILAR = 0.6  # of the heard words, in order
MAX_LONGER = 3  # words the reading may add or drop
RULE_WORDS: frozenset[str] = frozenset(
    word.casefold() for rule in RULES for word in rule.means.split()
)


def _in_order(need: Sequence[str], have: Sequence[str]) -> bool:
    it = iter(have)
    return all(any(word == other for other in it) for word in need)


def _keys(text: str) -> list[str]:
    return [w.key for w in split_words(text)]


def acceptable(
    heard: str,
    understood: str,
    *,
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
    allowed = {*_keys(heard), *RULE_WORDS, *FUNCTION_WORDS}
    for extra in (*alternatives, *hint_tuple):
        allowed.update(_keys(extra))
    new_keys = _keys(understood)
    if any(key not in allowed for key in new_keys):
        return False  # 3. a word from nowhere
    old_keys = _keys(heard)
    if abs(len(new_keys) - len(old_keys)) > MAX_LONGER:
        return False
    return SequenceMatcher(None, old_keys, new_keys).ratio() >= MIN_SIMILAR  # 4.


__all__ = ["RULE_WORDS", "acceptable"]
