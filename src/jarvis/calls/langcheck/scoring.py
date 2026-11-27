# src/jarvis/calls/langcheck/scoring.py
"""The language check's scorer (R18 B; plan 5.3) — pure functions, no I/O.

Pass bars, exactly as the plan states them:

    hearing   ≥ 90 % of the key facts right AND a character error rate ≤ 15 %, pooled over the
              ~20 phone-quality clips (Σ edits / Σ reference characters)
    voice     ≥ 90 % of the key facts survive the round trip (spoken, phone line, heard back by a
              different hearing option); then a person scores 3 samples 1–5: a mean of 4 or more
    speed     half of the replies start within 1.5 s of the other person stopping, and 9 in 10
              within 2.5 s

Key facts: in a test clip, every number, time and date of its reference transcript (digit
groups, separators dropped, leading zeros ignored, any script's digits); in a call sentence, those
and the words the brain marked as facts in its translation (a yes or no, a day, a name). A number
matches only a whole number heard (or a time heard as two numbers, "10 30"); a word matches when it
appears in the normalised transcript. A set of clips with no key fact at all does not pass: the
bar cannot be shown to hold.

Normalisation, before every comparison: NFKC, every script's decimal digits as ASCII, case
folded, punctuation and symbols (the danda too) as spaces, format characters (zero-width joiners)
removed, whitespace collapsed. Vowel signs and viramas are letters and stay.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

HEAR_FACTS_MIN = 0.90
HEAR_CER_MAX = 0.15
VOICE_FACTS_MIN = 0.90
HUMAN_SCORE_MIN = 4.0
HUMAN_SAMPLES = 3
HUMAN_SCORES = range(1, 6)
SPEED_FAST_S, SPEED_FAST_SHARE = 1.5, 0.5
SPEED_SLOW_S, SPEED_SLOW_SHARE = 2.5, 0.9
RUNAWAY_FACTOR = 3  # a transcript longer than 3 × the reference (+ slack) is cut, the rest counted
RUNAWAY_SLACK = 50

_NUMBER = re.compile(r"\d+(?:[.,:]\d+)*")
_DROP = frozenset({"P", "S", "C", "Z"})  # punctuation, symbols, control/format, separators


def _char(ch: str) -> str:
    if ch.isdecimal():
        return str(unicodedata.decimal(ch, 0))
    cat = unicodedata.category(ch)
    if cat == "Cf":  # zero-width joiners, bidi marks: inside a word, not between words
        return ""
    if cat[0] in _DROP:
        return " "
    return ch


def _ascii_digits(text: str) -> str:
    return "".join(str(unicodedata.decimal(c, 0)) if c.isdecimal() else c for c in text)


def normalise(text: str) -> str:
    """The comparable form of a transcript (see the module docstring)."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return " ".join("".join(_char(c) for c in folded).split())


def _digits(group: str) -> str:
    return re.sub(r"\D", "", group).lstrip("0") or "0"


def number_facts(text: str) -> tuple[str, ...]:
    """The numbers, times and dates of `text` as digit strings, in order."""
    plain = _ascii_digits(unicodedata.normalize("NFKC", text))
    return tuple(_digits(m.group(0)) for m in _NUMBER.finditer(plain))


def _numeric(fact: str) -> bool:
    return fact.isdecimal()


def _number_heard(fact: str, heard: tuple[str, ...]) -> bool:
    if fact in heard:
        return True
    pairs = (a + b.rjust(2, "0") for a, b in zip(heard, heard[1:], strict=False))
    return fact in pairs


def facts_found(facts: Sequence[str], heard: str) -> int:
    """How many of `facts` (digit strings or words) the transcript `heard` carries."""
    numbers = number_facts(heard)
    text = f" {normalise(heard)} "
    found = 0
    for fact in facts:
        if _numeric(fact):
            found += _number_heard(_digits(fact), numbers)
            continue
        word = normalise(fact)
        found += bool(word) and f" {word} " in text
    return found


def edit_distance(a: str, b: str) -> int:
    """Levenshtein distance (insert, delete, substitute: 1 each)."""
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


@dataclass(frozen=True)
class ClipScore:
    """One clip or one round-trip sentence, scored."""

    ref_chars: int
    edits: int
    facts_total: int
    facts_right: int

    @property
    def cer(self) -> float:
        return self.edits / self.ref_chars if self.ref_chars else float(self.edits > 0)


def _bounded_edits(ref: str, hyp: str) -> int:
    limit = RUNAWAY_FACTOR * len(ref) + RUNAWAY_SLACK
    extra = max(0, len(hyp) - limit)
    return edit_distance(ref, hyp[:limit]) + extra


def score_clip(reference: str, heard: str, facts: Sequence[str] | None = None) -> ClipScore:
    """`facts`: the key facts to look for (default: the reference's own numbers)."""
    ref, hyp = normalise(reference), normalise(heard)
    wanted = tuple(facts) if facts is not None else number_facts(reference)
    return ClipScore(
        ref_chars=len(ref),
        edits=_bounded_edits(ref, hyp),
        facts_total=len(wanted),
        facts_right=facts_found(wanted, heard),
    )


def cer(reference: str, heard: str) -> float:
    return score_clip(reference, heard, facts=()).cer


def _pct(x: float) -> str:
    return f"{round(x * 100)} %"


@dataclass(frozen=True)
class Verdict:
    passed: bool
    why: str  # plain words: what passed or what failed
    items: int
    cer: float | None = None
    facts_total: int = 0
    facts_right: int = 0

    @property
    def facts_rate(self) -> float | None:
        return self.facts_right / self.facts_total if self.facts_total else None


def _pooled(scores: Sequence[ClipScore]) -> tuple[float, int, int]:
    chars = sum(s.ref_chars for s in scores)
    edits = sum(s.edits for s in scores)
    pooled = edits / chars if chars else 1.0
    return pooled, sum(s.facts_total for s in scores), sum(s.facts_right for s in scores)


def _facts_failure(total: int, right: int, bar: float) -> str | None:
    if total == 0:
        return "no key facts to check in these samples"
    if right / total < bar:
        return f"{_pct(right / total)} of the key facts right (needs {_pct(bar)})"
    return None


def hearing_verdict(scores: Sequence[ClipScore]) -> Verdict:
    if not scores:
        return Verdict(False, "no clips were heard", 0)
    pooled, total, right = _pooled(scores)
    failures = [
        f
        for f in (
            _facts_failure(total, right, HEAR_FACTS_MIN),
            None
            if pooled <= HEAR_CER_MAX
            else f"a character error rate of {_pct(pooled)} (at most {_pct(HEAR_CER_MAX)})",
        )
        if f
    ]
    why = "; ".join(failures) or (
        f"{_pct(right / total)} of the key facts, character error rate {_pct(pooled)}"
    )
    return Verdict(not failures, why, len(scores), pooled, total, right)


def voice_verdict(scores: Sequence[ClipScore]) -> Verdict:
    if not scores:
        return Verdict(False, "no sentences were spoken", 0)
    pooled, total, right = _pooled(scores)
    failure = _facts_failure(total, right, VOICE_FACTS_MIN)
    why = failure or f"{_pct(right / total)} of the key facts survived the phone line"
    return Verdict(failure is None, why, len(scores), pooled, total, right)


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile (q in (0, 1])."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


@dataclass(frozen=True)
class SpeedVerdict:
    passed: bool
    why: str
    samples: int
    p50: float | None = None
    p90: float | None = None


def speed_verdict(seconds: Sequence[float]) -> SpeedVerdict:
    """`seconds`: how long each reply took to start after the other person stopped."""
    if not seconds:
        return SpeedVerdict(False, "no replies were timed", 0)
    n = len(seconds)
    fast = sum(s <= SPEED_FAST_S for s in seconds) / n
    slow = sum(s <= SPEED_SLOW_S for s in seconds) / n
    failures = []
    if fast < SPEED_FAST_SHARE:
        failures.append(f"{_pct(fast)} of replies started within {SPEED_FAST_S} s (needs half)")
    if slow < SPEED_SLOW_SHARE:
        failures.append(f"{_pct(slow)} started within {SPEED_SLOW_S} s (needs 9 in 10)")
    p50, p90 = percentile(seconds, 0.5), percentile(seconds, 0.9)
    why = "; ".join(failures) or f"half within {p50:.2f} s, 9 in 10 within {p90:.2f} s"
    return SpeedVerdict(not failures, why, n, p50, p90)


def human_verdict(scores: Sequence[int]) -> bool | None:
    """None: not yet heard by a native speaker. Else: the mean score is at least 4 (of 1–5)."""
    for s in scores:
        if isinstance(s, bool) or not isinstance(s, int) or s not in HUMAN_SCORES:
            raise ValueError("A score is a whole number from 1 to 5.")
    if not scores:
        return None
    return sum(scores) / len(scores) >= HUMAN_SCORE_MIN


__all__ = [
    "HEAR_CER_MAX",
    "HEAR_FACTS_MIN",
    "HUMAN_SAMPLES",
    "HUMAN_SCORE_MIN",
    "SPEED_FAST_S",
    "SPEED_FAST_SHARE",
    "SPEED_SLOW_S",
    "SPEED_SLOW_SHARE",
    "VOICE_FACTS_MIN",
    "ClipScore",
    "SpeedVerdict",
    "Verdict",
    "cer",
    "edit_distance",
    "facts_found",
    "hearing_verdict",
    "human_verdict",
    "normalise",
    "number_facts",
    "percentile",
    "score_clip",
    "speed_verdict",
    "voice_verdict",
]
