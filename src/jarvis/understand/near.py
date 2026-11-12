# src/jarvis/understand/near.py
"""Near-matches of heard words against the per-turn hints (R11.1; plan D8 step 1; Layer 2). Plain
code: `difflib` on letters and digits only, no model.

A run of one to four heard words is replaced by a hint only when exactly one hint fits and fits
closely (`SURE`), it starts with the same letter, and none of the words is protected or already
written by a rule. A looser fit (`NEAR`), or two hints that both fit, is "unsure": the caller asks
the fast tier or the owner. A lone word needs `MIN_FUZZY` letters and is never a common function
word; a hint that holds a digit is never used (numbers are not rewritten); a hint's own long
words also stand alone ("Budget 2027 final" offers "Budget" and "final"). A hint keeps its own
capitals when it is an acronym or a mixed name ("CSV", "PowerPoint"), else it takes the case of
the word it replaces.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from jarvis.understand.words import ACTION_WORDS, FUNCTION_WORDS, Word

SURE = 0.90  # a near-match this close, and the only one, is taken
NEAR = 0.80  # this close is worth asking about
MIN_FUZZY = 5  # letters a lone word needs before a near-match is tried
MAX_RUN = 4


def _squash(parts: list[str]) -> str:
    return "".join(ch for p in parts for ch in p.casefold() if ch.isalnum())


def _hint_runs(hints: tuple[str, ...]) -> dict[int, list[list[str]]]:
    """Hints as word lists by length; the long words of a many-word hint also stand alone."""
    runs: dict[int, list[list[str]]] = {}
    seen: set[tuple[str, ...]] = set()

    def keep(parts: list[str]) -> None:
        key = tuple(p.casefold() for p in parts)
        acts = any(k in ACTION_WORDS for k in key)
        if (
            key
            and key not in seen
            and not acts
            and not any(ch.isdigit() for p in parts for ch in p)
        ):
            seen.add(key)
            runs.setdefault(len(parts), []).append(parts)

    for hint in hints:
        parts = hint.split()
        if 1 <= len(parts) <= MAX_RUN:
            keep(parts)
        for part in parts if len(parts) > 1 else ():
            if len(part) >= MIN_FUZZY and part.isalpha() and part.casefold() not in FUNCTION_WORDS:
                keep([part])
    return runs


def _as_heard(hint_word: str, heard: Word) -> str:
    """A hint's word in the heard word's case, unless the hint is an acronym or a mixed name."""
    if hint_word.isupper() or any(ch.isupper() for ch in hint_word[1:]):
        return hint_word
    return hint_word.lower() if heard.core.islower() else hint_word


def near_matches(
    words: list[Word], free: list[bool], hints: tuple[str, ...]
) -> tuple[list[Word], set[str]]:
    """Near-matches against the hints: the words with sure ones replaced, and the hints that
    only nearly fit (unsure)."""
    runs = _hint_runs(hints)
    out = list(words)
    near: set[str] = set()
    taken = [not ok for ok in free]
    for n in sorted(runs, reverse=True):
        for i in range(len(out) - n + 1):
            span = out[i : i + n]
            if any(taken[i : i + n]) or any(w.ends_sentence for w in span[:-1]):
                continue
            if n == 1 and (len(span[0].core) < MIN_FUZZY or span[0].key in FUNCTION_WORDS):
                continue
            heard = _squash([w.core for w in span])
            if any(_squash(parts) == heard for parts in runs[n]):
                taken[i : i + n] = [True] * n  # already a hint, word for word
                continue
            fits = [
                (SequenceMatcher(None, heard, _squash(parts)).ratio(), parts)
                for parts in runs[n]
                if _squash(parts)[:1] == heard[:1]
            ]
            fits = [f for f in fits if f[0] >= NEAR]
            if len(fits) == 1 and fits[0][0] >= SURE:
                parts = fits[0][1]
                for k, part in enumerate(parts):
                    out[i + k] = span[k].with_core(_as_heard(part, span[k]))
                taken[i : i + n] = [True] * n
            elif fits:
                near.update(" ".join(parts) for _, parts in fits)
    return out, near


__all__ = ["MAX_RUN", "MIN_FUZZY", "NEAR", "SURE", "near_matches"]
