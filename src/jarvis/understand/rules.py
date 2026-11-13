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
  2. near-matches against the hints (`near.near_matches`: file names waiting on the composer or
     attached in this conversation, the conversation's own nouns, the owner's "Words to
     recognise"): a word run is replaced only when exactly one hint fits and fits closely; a
     looser or a double fit is "unsure" (`Outcome.near`).
  3. a word that is no word where the name of a thing belongs ("open the qzx file") is "unsure".

The result is sure, or it says why not; `jarvis.understand.service` then asks the fast tier
(only with the AI on) or asks the owner one short question. Capitals at the start of a sentence
are kept; a difference of capitals alone is not a change.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from jarvis.understand.context import (
    Ctx,
    When,
    add_slot,
    after_file_type,
    calendar_slot,
    called,
    csv_context,
    determiner_follows,
    file_next,
    mail_slot,
    number_for_to,
    power_point,
    reminder_slot,
    reminders_slot,
    the_app,
    thing_follows,
    to_slot,
    xl_sheet,
)
from jarvis.understand.near import near_matches
from jarvis.understand.words import (
    ACTION_WORDS,
    FUNCTION_WORDS,
    Level,
    Word,
    join_words,
    levels,
    split_words,
)

NOUN_SLOT: frozenset[str] = frozenset(
    "the a an my this that your our his her their to in from of open read on".split()
)
KNOWN_SHORT: frozenset[str] = frozenset(
    "csv pdf ppt pptx xls xlsx html sms upi otp gst pan kyc tv pc hr vs mr mrs dr st rd th nd "
    "km kg cm mm ml gb mb kb pm ok hmm mph kph ltd pvt cc bcc nd by my try why fly cry dry sky "
    "shy gym xl xxl xs".split()
)
_VOWELS = frozenset("aeiou")


@dataclass(frozen=True)
class Rule:
    heard: tuple[str, ...]  # the exact words, casefolded
    means: str
    when: When | None = None
    caps_ok: bool = False  # may apply to a Capitalised word that might be a name (SOFT)


def _many(forms: str, means: str, **kw: object) -> tuple[Rule, ...]:
    return tuple(Rule(tuple(f.split()), means, **kw) for f in forms.split(","))  # type: ignore[arg-type]


# The table. Longest matches win; a rule with `when` needs that context to hold.
RULES: tuple[Rule, ...] = (
    # ---- files
    *_many("c s v,cs v,see s v,sea s v", "CSV"),
    *_many("c s b,csb", "CSV", when=csv_context),
    *_many("csp", "CSV", when=file_next),
    *_many("p d f", "PDF"),
    *_many("p p t", "PPT"),
    *_many("power point", "PowerPoint", when=power_point),
    *_many("xl sheet,axel sheet,accel sheet", "Excel sheet", when=xl_sheet),
    *_many("xl sheets,axel sheets", "Excel sheets", when=xl_sheet),
    *_many("xl file,axel file,accel file", "Excel file"),
    *_many("xl files,axel files", "Excel files"),
    *_many("fail", "file", when=after_file_type),
    # ---- the calendar
    *_many("calender,calander,calandar,calendor,kalender", "calendar"),
    *_many("calenders,calanders", "calendars"),
    *_many("colander", "calendar", when=calendar_slot),
    # ---- small words the recogniser writes as letters
    *_many("d", "the", when=thing_follows, caps_ok=True),
    *_many("tu", "to", when=to_slot, caps_ok=True),
    *_many("too", "to", when=determiner_follows),
    *_many("2,two", "to", when=number_for_to),  # a number: never applied, only offered
    *_many("ad", "add", when=add_slot, caps_ok=True),
    # ---- its own name
    *_many(
        "jar vis,jarviz,jarvice,jarwis,jarvish,garvis,charvis,jarvas,javis,jarves",
        "JARVIS",
        when=called,
    ),
    # ---- reminders, mail, messages, the brief
    *_many("remainder", "reminder", when=reminder_slot),
    *_many("remainders", "reminders", when=reminders_slot),
    *_many("g mail,gee mail,g male", "Gmail"),
    *_many("e mail,e male", "email"),
    *_many("male", "mail", when=mail_slot),
    *_many("males", "mails", when=mail_slot),
    *_many("whats app,watsapp,whatsap", "WhatsApp"),
    *_many("what's app,what sap", "WhatsApp", when=the_app),
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
                tail=words[at + n - 1].tail,
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
    free = [
        lv is Level.NONE and not w and word.key not in ACTION_WORDS
        for lv, w, word in zip(after, wrote, sure, strict=True)
    ]
    fixed, near = near_matches(sure, free, hints)
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


__all__ = ["RULES", "Outcome", "Rule", "apply"]
