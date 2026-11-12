# src/jarvis/understand/rules.py
"""The fixed rules of "heard / understood as" (R11.1; plan D8 step 1, D21-B; Layer 2 input
processing). Free: plain code, no model, no network.

`apply(heard, hints)` reads the recogniser's words left to right:

  1. `RULES`: known mishearings of common words in Indian-English speech-to-text ("D" for "the",
     "Tu" for "to", "csb / c s v" for "CSV", "calender", "remainder" for "reminder", "male" for
     "mail", the ways "JARVIS" comes out). A rule names the exact heard words, what they become,
     and the words around them that make it safe (`when`). It never applies to a protected word
     (`words.levels`): then the sentence is left as it was heard and the corrected reading is
     only offered (`Outcome.candidate`), for the one question (D21-B).
  2. near-matches against the hints (file names waiting on the composer or attached in this
     conversation, the conversation's own nouns, the owner's "Words to recognise"): a word run
     is replaced only when exactly one hint fits and fits closely (`SURE`); a looser or a double
     fit is "unsure" (`Outcome.near`).
  3. a word that is no word where the name of a thing belongs ("open the qzx file") is "unsure".

The result is sure, or it says why not; `jarvis.understand.service` then asks the fast tier
(only with the AI on) or asks the owner one short question. Capitals at the start of a sentence
are kept; a difference of capitals alone is not a change.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from difflib import SequenceMatcher

from jarvis.understand.words import (
    FUNCTION_WORDS,
    STRONG_CUES,
    WEAK_CUES,
    Level,
    Word,
    join_words,
    levels,
    split_words,
)

SURE = 0.90  # a near-match this close, and the only one, is taken
NEAR = 0.80  # this close is worth asking about
MIN_FUZZY = 5  # letters a lone word needs before a near-match is tried
MAX_RUN = 4

DETERMINERS: frozenset[str] = frozenset(
    "the my a an this that these those your our his her their d".split()
)
FILE_WORDS: frozenset[str] = frozenset(
    "file files fail sheet sheets data export attachment document doc".split()
)
FILE_TYPES: frozenset[str] = frozenset(
    "csv pdf excel word powerpoint ppt text zip markdown xl".split()
)
COMMON_VERBS: frozenset[str] = frozenset(
    "add put open read send move copy attach summarise summarize check show find get take use "
    "see delete save share print upload import schedule book set create update sync load list "
    "explain analyse analyze review plan compare search mark close edit rename".split()
)
MAIL_VERBS: frozenset[str] = frozenset(
    "send sent check read open write draft forward reply compose get".split()
)
NOUN_SLOT: frozenset[str] = frozenset(
    "the a an my this that your our his her their to in from of open read on".split()
)
KNOWN_SHORT: frozenset[str] = frozenset(
    "csv pdf ppt pptx xls xlsx html sms upi otp gst pan kyc tv pc hr vs mr mrs dr st rd th nd "
    "km kg cm mm ml gb mb kb pm ok hmm mph kph ltd pvt cc bcc nd by my try why fly cry dry sky "
    "shy gym".split()
)
_VOWELS = frozenset("aeiou")


@dataclass(frozen=True)
class Ctx:
    """What a rule may look at: the words already written (after earlier rules), the heard
    words still to come, and the hints."""

    before: tuple[str, ...]  # keys of the output so far
    after: tuple[Word, ...]  # heard words after the match
    after_levels: tuple[Level, ...]
    hints: frozenset[str]  # every hint word, casefolded

    @property
    def prev(self) -> str:
        return self.before[-1] if self.before else ""

    @property
    def prev2(self) -> str:
        return self.before[-2] if len(self.before) > 1 else ""

    @property
    def next(self) -> str:
        return self.after[0].key if self.after else ""


When = Callable[[Ctx], bool]


@dataclass(frozen=True)
class Rule:
    heard: tuple[str, ...]  # the exact words, casefolded
    means: str
    when: When | None = None
    caps_ok: bool = False  # may apply to a Capitalised word that might be a name (SOFT)


def _file_next(c: Ctx) -> bool:
    return c.next in FILE_WORDS


def _csv_context(c: Ctx) -> bool:
    return c.next in FILE_WORDS or "csv" in c.hints


def _after_file_type(c: Ctx) -> bool:
    return c.prev in FILE_TYPES


def _calendar_slot(c: Ctx) -> bool:
    return c.prev in {"my", "the", "to", "google", "in", "on"}


def _thing_follows(c: Ctx) -> bool:
    """ "D" is "the": a plain word follows, and what came before is no person."""
    if not c.after or c.after_levels[0] is Level.HARD:
        return False
    nxt = c.after[0]
    plain = nxt.core.isalpha() and nxt.key not in FUNCTION_WORDS
    named = len(nxt.core) > 1 and nxt.core[0].isupper() and not nxt.core.isupper()
    known_before = not c.before or c.prev in FUNCTION_WORDS or c.prev in COMMON_VERBS
    return plain and not named and known_before


def _determiner_follows(c: Ctx) -> bool:
    return c.next in DETERMINERS


def _to_slot(c: Ctx) -> bool:
    """ "Tu" is "to": a determiner follows and the word before takes no person."""
    return c.next in DETERMINERS and c.prev not in STRONG_CUES and c.prev not in WEAK_CUES


def _number_for_to(c: Ctx) -> bool:
    return bool(c.before) and c.next in DETERMINERS and c.prev not in {"add", "the", "all"}


def _add_slot(c: Ctx) -> bool:
    opens = not c.before or c.prev in {"please", "jarvis", "and", "then", "also", "sir"}
    return opens and c.next in {
        *("this", "that", "these", "those", "it", "the", "a", "an", "my", "d", "them", "all"),
        "both",
    }


def _reminder_slot(c: Ctx) -> bool:
    asked = c.prev in {"a", "the", "my", "set", "add", "create", "new", "another", "one", "this"}
    return asked and c.next not in {"of", "is", "was", "when"}


def _reminders_slot(c: Ctx) -> bool:
    return c.prev in {"my", "the", "all", "any", "set", "show", "list"} and c.next != "of"


def _mail_slot(c: Ctx) -> bool:
    if c.prev in MAIL_VERBS or c.prev == "unread":
        return True
    return c.prev in {"a", "an", "the", "my", "new", "this"} and c.prev2 in MAIL_VERBS


def _many(forms: str, means: str, **kw: object) -> tuple[Rule, ...]:
    return tuple(Rule(tuple(f.split()), means, **kw) for f in forms.split(","))  # type: ignore[arg-type]


# The table. Longest matches win; a rule with `when` needs that context to hold.
RULES: tuple[Rule, ...] = (
    # ---- files
    *_many("c s v,c s b,cs v,see s v,sea s v", "CSV"),
    *_many("csb", "CSV", when=_csv_context),
    *_many("csp", "CSV", when=_file_next),
    *_many("p d f", "PDF"),
    *_many("p p t", "PPT"),
    *_many("power point", "PowerPoint"),
    *_many("xl sheet,axel sheet,accel sheet", "Excel sheet"),
    *_many("xl sheets,axel sheets", "Excel sheets"),
    *_many("xl file,axel file,accel file", "Excel file"),
    *_many("xl files,axel files", "Excel files"),
    *_many("fail", "file", when=_after_file_type),
    # ---- the calendar
    *_many("calender,calander,calandar,calendor,kalender", "calendar"),
    *_many("calenders,calanders", "calendars"),
    *_many("colander", "calendar", when=_calendar_slot),
    # ---- small words the recogniser writes as letters
    *_many("d", "the", when=_thing_follows, caps_ok=True),
    *_many("tu", "to", when=_to_slot, caps_ok=True),
    *_many("too", "to", when=_determiner_follows),
    *_many("2,two", "to", when=_number_for_to),  # a number: never applied, only offered
    *_many("ad", "add", when=_add_slot, caps_ok=True),
    # ---- its own name
    *_many("jar vis,jarviz,jarvice,jarwis,jarvish,garvis,charvis,jarvas,javis,jarves", "JARVIS"),
    # ---- reminders, mail, messages, the brief
    *_many("remainder", "reminder", when=_reminder_slot),
    *_many("remainders", "reminders", when=_reminders_slot),
    *_many("g mail,gee mail,g male", "Gmail"),
    *_many("e mail,e male", "email"),
    *_many("male", "mail", when=_mail_slot),
    *_many("males", "mails", when=_mail_slot),
    *_many("whats app,what's app,watsapp,whatsap,what sap", "WhatsApp"),
    *_many("mourning brief", "morning brief"),
)


@dataclass(frozen=True)
class Outcome:
    text: str  # the sure reading (the heard words when a correction was only offered)
    changed: bool
    sure: bool
    candidate: str | None = None  # the reading a protected word stopped the rules from taking
    near: tuple[str, ...] = ()  # hints that nearly fit
    unknown: str | None = None  # a word that is no word, where a thing's name belongs


def _same(a: str, b: str) -> bool:
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


def _match(words: list[Word], i: int, ctx_of: Callable[[int], Ctx]) -> Rule | None:
    """The longest rule whose heard words start at `i` and whose context holds."""
    best: Rule | None = None
    for rule in RULES:
        n = len(rule.heard)
        if best is not None and n <= len(best.heard):
            continue
        if tuple(w.key for w in words[i : i + n]) != rule.heard:
            continue
        if any(w.ends_sentence for w in words[i : i + n - 1]):
            continue
        if rule.when is None or rule.when(ctx_of(n)):
            best = rule
    return best


def _table(
    words: list[Word], marks: list[Level], hints: frozenset[str]
) -> tuple[list[Word], list[Word], list[bool], bool]:
    """(the sure reading, the reading with stopped rules applied too, which sure words a rule
    wrote, whether a protected word stopped one)."""
    sure: list[Word] = []
    offered: list[Word] = []
    wrote: list[bool] = []
    stopped = False
    i = 0
    while i < len(words):

        def ctx_of(n: int, at: int = i) -> Ctx:
            return Ctx(
                before=tuple(w.key for w in offered),
                after=tuple(words[at + n :]),
                after_levels=tuple(marks[at + n :]),
                hints=hints,
            )

        rule = _match(words, i, ctx_of)
        if rule is None:
            sure.append(words[i])
            offered.append(words[i])
            wrote.append(False)
            i += 1
            continue
        n = len(rule.heard)
        level = max(marks[i : i + n])
        new = Word(words[i].head, rule.means, words[i + n - 1].tail)
        offered.append(new)
        if level is Level.HARD or (level is Level.SOFT and not rule.caps_ok):
            stopped = True
            sure.extend(words[i : i + n])
            wrote.extend([False] * n)
        else:
            sure.append(new)
            wrote.append(True)
        i += n
    return sure, offered, wrote, stopped


def _squash(parts: list[str]) -> str:
    return "".join(ch for p in parts for ch in p.casefold() if ch.isalnum())


def _hint_runs(hints: tuple[str, ...]) -> dict[int, list[list[str]]]:
    """Hints as word lists by length; the long words of a many-word hint also stand alone."""
    runs: dict[int, list[list[str]]] = {}
    seen: set[tuple[str, ...]] = set()

    def keep(parts: list[str]) -> None:
        key = tuple(p.casefold() for p in parts)
        if key and key not in seen and not any(ch.isdigit() for p in parts for ch in p):
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


def _fuzzy(
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


def _unknown(words: list[Word], free: list[bool], hints: frozenset[str]) -> str | None:
    """A lowercase word with no vowel (or a stray letter) where a thing's name belongs."""
    for i, word in enumerate(words):
        if not free[i] or not word.core.isalpha() or not word.core.islower():
            continue
        key = word.key
        if key in KNOWN_SHORT or key in hints or key in FUNCTION_WORDS:
            continue
        stray = len(key) == 1 and key not in {"a", "i"}
        no_vowel = 2 <= len(key) <= 6 and not (_VOWELS & set(key)) and "y" not in key
        if (stray or no_vowel) and i > 0 and words[i - 1].key in NOUN_SLOT:
            return word.core
    return None


def _capitals(words: list[Word], heard: list[Word]) -> list[Word]:
    """A sentence that began with a capital still does."""
    out = list(words)
    starts = True
    for i, word in enumerate(out):
        if starts and word.core[:1].islower() and heard and heard[0].core[:1].isupper() and i == 0:
            out[i] = word.with_core(word.core[:1].upper() + word.core[1:])
        starts = word.ends_sentence
    return out


def apply(heard: str, hints: tuple[str, ...] = ()) -> Outcome:
    """The fixed rules on one heard sentence (see the module docstring)."""
    words = split_words(heard)
    if not words:
        return Outcome(text=" ".join(heard.split()), changed=False, sure=True)
    hint_words = frozenset(part.casefold() for hint in hints for part in hint.split())
    marks = levels(words, hints)
    sure, offered, wrote, stopped = _table(words, marks, hint_words)
    if stopped:
        return Outcome(
            text=join_words(words),
            changed=False,
            sure=False,
            candidate=join_words(_capitals(offered, words)),
        )
    after = levels(sure, hints)
    free = [lv is Level.NONE and not w for lv, w in zip(after, wrote, strict=True)]
    fixed, near = _fuzzy(sure, free, hints)
    still_free = [f and a.core == b.core for f, a, b in zip(free, fixed, sure, strict=True)]
    unknown = _unknown(fixed, still_free, hint_words)
    text = join_words(_capitals(fixed, words))
    return Outcome(
        text=text,
        changed=not _same(text, heard),
        sure=not near and unknown is None,
        near=tuple(sorted(near)),
        unknown=unknown,
    )


__all__ = ["NEAR", "RULES", "SURE", "Outcome", "Rule", "apply"]
