# src/jarvis/voice/session_score.py
"""Scoring the voice session (R5.2 row 81; plan 3.3, 5): pure functions, no I/O.

Every listening engine (the browser's, Google with his words, the laptop's Whispers) heard the
held-out prompts; each is scored by word error (Σ word edits / Σ reference words, pooled) and
command accuracy (a command or request is right when its key phrase is in what was heard). When
two engines heard different prompts, all are ranked on the prompts every one of them heard (if
there are at least `MIN_PROMPTS`), so a harder block can't favour the engine that missed it.

Before comparing, both sides are made comparable: R18's `normalise` (NFKC, case folded,
punctuation as spaces; injected, `jarvis.calls.langcheck.scoring.normalise`), then the forms an
engine may choose for the same words: "2,400" is 2400, "₹450" is "450 rupees", "%" is "percent",
"a.m." is "am", and number words are digits ("six forty five" is "6 45", "two thousand four
hundred" is "2400").

The chosen engine (`choose`): the best by word error; but a laptop engine within the plan's
2 points of it, with commands >= 95 %, is chosen instead (free, and his audio stays home), and
Whisper medium only when it is clearly better than small (D2). Corrections (`learn_corrections`):
the chosen engine's mishearings that repeat (seen twice or more), 1-3 heard words for 1-5 meant
words, never from the numbers block and never a number, money or code word (`Correction` refuses
them), never a phrase he really says in another prompt. Transcripts are never logged.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from jarvis.localspeech.protocol import PromptKind
from jarvis.voice.commands import BASE_PHRASES
from jarvis.voice.profile import (
    BARS,
    CORRECTIONS_MAX,
    MEANT_WORDS_MAX,
    Correction,
    EngineScore,
    ListenEngine,
    ProfileBars,
    Prompt,
)
from jarvis.voice.session_prompts import scored

Normalise = Callable[[str], str]
MIN_PROMPTS: Final = 10  # an engine heard fewer held-out prompts than this: not ranked
REPEAT_MIN: Final = 2  # "mishearings that repeat"
HEARD_SPAN_MAX: Final = 3
# among equals: the laptop (free, private) first, then Google, then the browser
PREFERENCE: Final[tuple[ListenEngine, ...]] = (
    ListenEngine.WHISPER_SMALL,
    ListenEngine.WHISPER_MEDIUM,
    ListenEngine.GOOGLE,
    ListenEngine.BROWSER,
)
_UNITS: Final = dict(
    zip("zero one two three four five six seven eight nine".split(), range(10), strict=True)
)
_TEENS: Final = dict(
    zip(
        "ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(),
        range(10, 20),
        strict=True,
    )
)
_TENS: Final = dict(
    zip(
        "twenty thirty forty fifty sixty seventy eighty ninety".split(),
        range(20, 100, 10),
        strict=True,
    )
)
_SMALL: Final = _UNITS | _TEENS
_NUMBER_WORDS: Final = frozenset(_SMALL) | frozenset(_TENS) | {"hundred", "thousand"}
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{2})")
_RUPEES = re.compile(r"(?:₹|\brs\b\.?)\s*(\d+)", re.IGNORECASE)
_WORD = re.compile(r"[^\W_]+(?:['\u2019][^\W_]+)*")
_BASE: Final = frozenset(p.casefold() for p in BASE_PHRASES)


@dataclass(frozen=True)
class Heard:
    """What one engine heard for one prompt (`ms`: how long it took, when known)."""

    engine: ListenEngine
    prompt_id: str
    text: str
    ms: int | None = None


# ---- making two transcripts comparable -----------------------------------------------------------
def _pre(text: str) -> str:
    text = _THOUSANDS.sub("", text)
    text = _RUPEES.sub(r"\1 rupees", text)
    return text.replace("%", " percent ").replace("&", " and ")


def _tail(word: str) -> bool:
    return word in _SMALL or word in _TENS


def _number(words: Sequence[str], i: int) -> tuple[int | None, int]:
    """The number spelled from words[i] on (and where it ends), or (None, i)."""
    total = cur = 0
    last, j = "", i
    while j < len(words):
        w = words[j]
        if w in _SMALL:
            if last in ("unit", "teen") or (last == "tens" and (w in _TEENS or _SMALL[w] == 0)):
                break
            cur, last = cur + _SMALL[w], "teen" if w in _TEENS else "unit"
        elif w in _TENS:
            if last in ("unit", "teen", "tens"):
                break
            cur, last = cur + _TENS[w], "tens"
        elif w == "hundred" and last in ("unit", "teen", "tens"):
            cur, last = cur * 100, "hundred"
        elif w == "thousand" and last and last != "thousand" and total == 0:
            total, cur, last = (total + cur) * 1000, 0, "thousand"
        elif w == "and" and last == "hundred" and words[j + 1 : j + 2] and _tail(words[j + 1]):
            j += 1
            continue
        else:
            break
        j += 1
    return (total + cur, j) if last else (None, i)


def _canonical(words: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(words):
        value, end = _number(words, i)
        if value is not None:
            out.append(str(value))
            i = end
            continue
        pair = tuple(words[i : i + 2])
        if pair in (("a", "m"), ("p", "m")) and out and out[-1].isdigit():
            out.append(pair[0] + "m")
            i += 2
            continue
        if pair == ("per", "cent"):
            out.append("percent")
            i += 2
            continue
        out.append(words[i])
        i += 1
    return out


def tokens(text: str, normalise: Normalise) -> list[str]:
    """`text` as the words compared: R18's normalise, then one form for numbers and units."""
    return _canonical(normalise(_pre(text)).split())


def words_of(text: str) -> list[str]:
    """`text` as an engine wrote its words (case folded, apostrophes kept, one form for numbers):
    a correction's heard side must match the engine's own text, which it is applied to."""
    plain = _pre(text).replace("\u2019", "'")
    return _canonical([w.casefold() for w in _WORD.findall(plain)])


# ---- word error ---------------------------------------------------------------------------------
Op = tuple[str, str | None, str | None]  # ("=" | "s" | "d" | "i", reference word, heard word)


def align(ref: Sequence[str], hyp: Sequence[str]) -> list[Op]:
    """The fewest word edits turning `ref` into `hyp` (Levenshtein, with its path)."""
    n, m = len(ref), len(hyp)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            same = ref[i - 1] == hyp[j - 1]
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (not same))
    ops: list[Op] = []
    i, j = n, m
    while i or j:
        if i and j and d[i][j] == d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            ops.append(("=" if ref[i - 1] == hyp[j - 1] else "s", ref[i - 1], hyp[j - 1]))
            i, j = i - 1, j - 1
        elif i and d[i][j] == d[i - 1][j] + 1:
            ops.append(("d", ref[i - 1], None))
            i -= 1
        else:
            ops.append(("i", None, hyp[j - 1]))
            j -= 1
    return ops[::-1]


def edits(ref: Sequence[str], hyp: Sequence[str]) -> int:
    return sum(op != "=" for op, _, _ in align(ref, hyp))


def _contains(words: Sequence[str], part: Sequence[str]) -> bool:
    k = len(part)
    return k > 0 and any(list(words[i : i + k]) == list(part) for i in range(len(words) - k + 1))


# ---- the comparison ------------------------------------------------------------------------------
def _by_engine(heard: Iterable[Heard], ids: set[str]) -> dict[ListenEngine, dict[str, Heard]]:
    out: dict[ListenEngine, dict[str, Heard]] = {}
    for h in heard:
        if h.prompt_id in ids:
            out.setdefault(h.engine, {})[h.prompt_id] = h
    return out


def _score(
    engine: ListenEngine,
    rows: Mapping[str, Heard],
    prompts: Mapping[str, Prompt],
    keys: Mapping[str, str],
    normalise: Normalise,
) -> EngineScore:
    words = errors = asked = right = 0
    for pid, h in rows.items():
        ref, hyp = tokens(prompts[pid].text, normalise), tokens(h.text, normalise)
        words, errors = words + len(ref), errors + edits(ref, hyp)
        if prompts[pid].kind is PromptKind.COMMAND and pid in keys:
            asked += 1
            right += _contains(hyp, tokens(keys[pid], normalise))
    ms = [h.ms for h in rows.values() if h.ms is not None]
    return EngineScore(
        engine=engine,
        wer=round(errors / words, 4) if words else 1.0,
        commands=round(right / asked, 4) if asked else 0.0,
        prompts=len(rows),
        median_ms=int(statistics.median(ms)) if ms else None,
    )


def score_engines(
    prompts: Sequence[Prompt],
    keys: Mapping[str, str],
    heard: Iterable[Heard],
    normalise: Normalise,
) -> tuple[EngineScore, ...]:
    """Every engine that heard at least `MIN_PROMPTS` held-out prompts, best first."""
    pmap = {p.id: p for p in prompts if scored(p)}
    found = {e: r for e, r in _by_engine(heard, set(pmap)).items() if len(r) >= MIN_PROMPTS}
    if not found:
        return ()
    common = set.intersection(*(set(r) for r in found.values()))
    if len(common) >= MIN_PROMPTS:
        found = {e: {p: h for p, h in r.items() if p in common} for e, r in found.items()}
    scores = [_score(e, r, pmap, keys, normalise) for e, r in found.items()]
    return tuple(sorted(scores, key=lambda s: (s.wer, -s.commands, PREFERENCE.index(s.engine))))


def choose(ranking: Sequence[EngineScore], bars: ProfileBars = BARS) -> ListenEngine | None:
    """The best engine, or a laptop one within the bar's margin of it (see the module doc)."""
    if not ranking:
        return None
    best, margin = ranking[0], bars.wer_margin_points / 100
    near = {
        s.engine: s
        for s in ranking
        if s.engine.on_laptop and s.commands >= bars.commands_min and s.wer <= best.wer + margin
    }
    small, medium = near.get(ListenEngine.WHISPER_SMALL), near.get(ListenEngine.WHISPER_MEDIUM)
    if small is not None and (medium is None or medium.wer >= small.wer - margin):
        return small.engine
    if medium is not None:
        return medium.engine
    return best.engine


def meets_bar(ranking: Sequence[EngineScore], chosen: ListenEngine | None) -> bool | None:
    """The plan's recognition bar (section 5) for the chosen engine; None when there is no cloud
    engine to compare with."""
    pick = next((s for s in ranking if s.engine is chosen), None)
    cloud = [s.wer for s in ranking if not s.engine.on_laptop]
    if pick is None or not cloud:
        return None
    return BARS.recognition_ok(
        chosen_wer=pick.wer, best_cloud_wer=min(cloud), commands=pick.commands
    )


# ---- corrections and new words ------------------------------------------------------------------
def _cased(text: str) -> dict[str, str]:
    return {w.casefold(): w for w in _WORD.findall(text)}


def _spans(ops: Sequence[Op]) -> Iterable[tuple[list[str], list[str]]]:
    ref: list[str] = []
    hyp: list[str] = []
    for op, r, h in [*ops, ("=", None, None)]:
        if op != "=":
            ref += [r] if r is not None else []
            hyp += [h] if h is not None else []
            continue
        if ref or hyp:
            yield ref, hyp
        ref, hyp = [], []


def learn_corrections(prompts: Sequence[Prompt], heard: Iterable[Heard]) -> tuple[Correction, ...]:
    """The chosen engine's repeating mishearings (`heard`: that engine's rows only)."""
    pmap = {p.id: p for p in prompts if scored(p) and p.kind is not PromptKind.NUMBERS}
    refs = [words_of(p.text) for p in prompts]
    seen: Counter[tuple[str, str]] = Counter()
    shown: dict[str, str] = {}
    for h in heard:
        prompt = pmap.get(h.prompt_id)
        if prompt is None:
            continue
        cased = _cased(prompt.text)
        ops = align(words_of(prompt.text), words_of(h.text))
        for ref, hyp in _spans(ops):
            if not (1 <= len(hyp) <= HEARD_SPAN_MAX and 1 <= len(ref) <= MEANT_WORDS_MAX):
                continue
            if any(_contains(r, hyp) for r in refs):  # he says those words elsewhere
                continue
            meant = " ".join(cased.get(w, w) for w in ref)
            seen[(" ".join(hyp), meant.casefold())] += 1
            shown.setdefault(meant.casefold(), meant)
    best: dict[str, tuple[int, str]] = {}
    for (said, meant), count in seen.most_common():
        if count >= REPEAT_MIN and said not in best and said != meant:
            best[said] = (count, shown[meant])
    out: list[Correction] = []
    for said, (count, meant) in best.items():
        try:
            out.append(Correction(heard=said, meant=meant, seen=count))
        except ValueError:  # a number, money or code word, a digit, too short: never corrected
            continue
    return tuple(out[:CORRECTIONS_MAX])


def _proper(meant: str, prompts: Iterable[Prompt]) -> bool:
    """Every word of `meant` is capitalised where he read it, and not as a sentence's first word."""
    for p in prompts:
        words = _WORD.findall(p.text)
        for i in range(1, len(words)):
            got = words[i : i + len(meant.split())]
            if " ".join(got) == meant and all(w[:1].isupper() for w in got):
                return True
    return False


def new_words(
    corrections: Iterable[Correction],
    prompts: Sequence[Prompt],
    typed: Iterable[str],
    existing: Iterable[str],
) -> tuple[str, ...]:
    """The words that join his "words to recognise": the names and places he typed when he
    started, then the names among the corrections' meant words; never one already there or one
    the voice service always sends (`BASE_PHRASES`)."""
    have = {w.casefold() for w in existing} | _BASE
    out: dict[str, str] = {}
    names = [c.meant for c in corrections if _proper(c.meant, prompts)]
    for w in [*typed, *names]:
        key = w.casefold()
        if key not in have:
            out.setdefault(key, w)
    return tuple(out.values())


__all__ = [
    "MIN_PROMPTS",
    "PREFERENCE",
    "REPEAT_MIN",
    "Heard",
    "Normalise",
    "align",
    "choose",
    "edits",
    "learn_corrections",
    "meets_bar",
    "new_words",
    "score_engines",
    "tokens",
    "words_of",
]
