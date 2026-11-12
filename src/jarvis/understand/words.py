# src/jarvis/understand/words.py
"""A heard sentence as words, and which of them must never be rewritten (R11.1; plan D8, D21-B;
Layer 2 input processing). Pure and deterministic: no model, no network, no storage.

`split_words` keeps each word with the punctuation that touched it, so a corrected sentence goes
back together as it was said. `levels` marks every word:

    HARD   never changed by a rule, a near-match or the model. A number or anything with a digit
           in it (a time, a date, an amount, a phone number), a number word, a money or time
           word, a weekday or month, an e-mail address, and a person's name as far as plain code
           can tell: the word after "call / tell / ask / Mr / Dr ...", a Capitalised word after
           "to / with / from / for", an initial beside a name ("D Raja", "Meera D").
    SOFT   a Capitalised word in the middle of a sentence that may be a name. A near-match and
           the model may not touch it; only a rule written for that exact word may.
    NONE   everything else.

Erring toward protection is the design: when the only possible correction would touch a protected
word, JARVIS asks its one question instead of acting (D21-B).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum

_HEAD = "\"'“‘([{<"
_TAIL = ".,;:!?\"'”’)]}>…"
_SENTENCE_END = frozenset(".!?")
_EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")

NUMBER_WORDS: frozenset[str] = frozenset(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty "
    "ninety hundred thousand lakh lakhs crore crores million billion half quarter dozen double "
    "first second third fourth fifth sixth seventh eighth ninth tenth".split()
)
MONEY_WORDS: frozenset[str] = frozenset("rupee rupees rs paise paisa inr".split())
TIME_WORDS: frozenset[str] = frozenset("am pm a.m p.m o'clock oclock noon midnight".split())
DATE_WORDS: frozenset[str] = frozenset(
    "monday tuesday wednesday thursday friday saturday sunday mon tue tues wed thu thur thurs "
    "fri sat january february march april june july august september october november december "
    "jan feb mar apr jun jul aug sep sept oct nov dec today tomorrow yesterday tonight".split()
)
# after one of these the next word is who it is for, whatever its case
STRONG_CUES: frozenset[str] = frozenset(
    "call ring phone text message msg ping mail email tell ask remind invite meet inform thank "
    "wish give gave send sent show pay paid forward lend bring mr mrs ms miss dr prof shri smt "
    "sri".split()
)
# ... unless that next word is plainly a thing ("text file", "send message")
PLAIN_NOUNS: frozenset[str] = frozenset(
    "file files fail sheet sheets message messages draft drafts address box id".split()
)
# after one of these a Capitalised word is taken for a name
WEAK_CUES: frozenset[str] = frozenset("to with from for by and cc".split())
FUNCTION_WORDS: frozenset[str] = frozenset(
    "a an the this that these those my your our his her its their some any all both each every "
    "no not i you he she it we they me him them us am is are was were be been being do does did "
    "have has had will would shall should can could may might must to of in on at by for with "
    "from into onto about over under after before between through during until till as than "
    "and or but so if then else when while where why how what which who whom whose there here "
    "now today please just also too very more most less up down out off again once only still "
    "yes ok okay sir madam ready done back later soon yet already".split()
)
# Capitalised in the middle of a sentence, and not a person
KNOWN_CAPITALS: frozenset[str] = frozenset(
    "i jarvis sir madam google gmail calendar drive excel word powerpoint whatsapp telegram "
    "youtube maps photos india kerala english hindi malayalam odia".split()
)
# What a request DOES (code review M1). Derived from the gateway's tool verbs (the second word
# of `calendar_create_event`, `gmail_send`, `task_delete`, `memory_forget`, `bill_pay_prepare`,
# `nudge_snooze`, `deleted_restore`, `home_arm`, ...: `tests/test_r11_1_b_guard.py` checks every
# registered tool's verb is here) plus the ways a spoken request names an action. No correction,
# by a rule's near-match or by the fast tier, may change, add or drop one of these.
ACTION_VERBS: tuple[str, ...] = tuple(
    "add append approve archive arm ask attach block book borrow buy call cancel change charge "
    "check clear close compose confirm connect control copy create decline delete deny deposit "
    "detach dial disable disarm discard disconnect dismiss done download draft edit email empty "
    "enable erase export find forget forward get give grant hide import install invite link "
    "list lend lock log look mail mark message move mute note notify open order pause pay phone "
    "ping play post prepare print publish put read record refund reject remind remove rename "
    "renew reply research reset restore resume return revoke ring run save schedule search sell "
    "send set share show sign snooze start stop submit subscribe suggest switch sync take tell "
    "text track transfer trash turn undo unblock unhide uninstall unlink unlock unmute "
    "unsubscribe update upload wipe withdraw write".split()
)
_IRREGULAR: dict[str, tuple[str, ...]] = {
    "buy": ("bought",),
    "borrow": ("borrowed",),
    "find": ("found",),
    "forget": ("forgot", "forgotten"),
    "get": ("got", "gotten"),
    "give": ("gave", "given"),
    "hide": ("hid", "hidden"),
    "lend": ("lent",),
    "pay": ("paid",),
    "read": ("read",),
    "ring": ("rang", "rung"),
    "run": ("ran",),
    "sell": ("sold",),
    "send": ("sent",),
    "set": ("set",),
    "take": ("took", "taken"),
    "tell": ("told",),
    "undo": ("undid", "undone"),
    "withdraw": ("withdrew", "withdrawn"),
    "write": ("wrote", "written"),
}
_DOUBLED = frozenset("cancel ship stop swap plan".split())  # cancelled, stopped, ...


def _forms(verb: str) -> set[str]:
    """A verb and its plain forms: adds, added, adding (irregular pasts from `_IRREGULAR`)."""
    stem = verb[:-1] if verb.endswith("e") and not verb.endswith("ee") else verb
    last = verb[-1]
    doubled = verb + last if verb in _DOUBLED else verb
    third = verb + ("es" if verb.endswith(("s", "x", "ch", "sh")) else "s")
    past = verb + "d" if verb.endswith("e") else doubled + "ed"
    if verb.endswith("y") and verb[-2:-1] not in "aeiou":
        third, past = verb[:-1] + "ies", verb[:-1] + "ied"
    return {verb, third, past, stem + "ing", doubled + "ing", *_IRREGULAR.get(verb, ())}


ACTION_WORDS: frozenset[str] = frozenset(f for v in ACTION_VERBS for f in _forms(v))


class Level(IntEnum):
    NONE = 0
    SOFT = 1
    HARD = 2


@dataclass(frozen=True)
class Word:
    head: str  # punctuation before the word
    core: str
    tail: str  # punctuation after it

    @property
    def key(self) -> str:
        return self.core.casefold()

    @property
    def ends_sentence(self) -> bool:
        return any(ch in _SENTENCE_END for ch in self.tail)

    def with_core(self, core: str) -> Word:
        return Word(self.head, core, self.tail)

    def text(self) -> str:
        return self.head + self.core + self.tail


def split_words(text: str) -> list[Word]:
    """The sentence's words in order, each with the punctuation that touched it."""
    out: list[Word] = []
    for raw in text.split():
        if _EMAIL.fullmatch(raw.strip(_HEAD + _TAIL)):
            core = raw.strip(_HEAD + _TAIL)
            start = raw.index(core)
            out.append(Word(raw[:start], core, raw[start + len(core) :]))
            continue
        start, end = 0, len(raw)
        while start < end and raw[start] in _HEAD:
            start += 1
        while end > start and raw[end - 1] in _TAIL:
            end -= 1
        if start < end:
            out.append(Word(raw[:start], raw[start:end], raw[end:]))
        elif out:  # punctuation standing alone: it belongs to the word before it
            out[-1] = Word(out[-1].head, out[-1].core, out[-1].tail + raw)
    return out


def join_words(words: list[Word]) -> str:
    return " ".join(w.text() for w in words)


def _capitalised(core: str) -> bool:
    """Title-like ("Priya", "Raja"): a capital first letter and a small letter after it."""
    return len(core) >= 2 and core[0].isupper() and any(ch.islower() for ch in core[1:])


def _initial(core: str) -> bool:
    return len(core) == 1 and core.isalpha() and core.isupper()


def _starts_sentence(words: list[Word], i: int) -> bool:
    return i == 0 or words[i - 1].ends_sentence


def _by_itself(word: Word) -> Level:
    """What the word is on its own: a number, money, a time, a date, an e-mail address."""
    return Level.HARD if fixed_key(word.key) or _EMAIL.fullmatch(word.core) else Level.NONE


def _may_be_name(word: Word) -> bool:
    return (
        _capitalised(word.core)
        and word.key not in FUNCTION_WORDS
        and word.key not in KNOWN_CAPITALS
    )


def levels(words: list[Word], hints: tuple[str, ...] = ()) -> list[Level]:
    """How protected each word is (see the module docstring). `hints` change nothing here on
    purpose: a name that is also a hint (a file called "Riya notes", a name in the owner's own
    word list) is still a name nothing may rewrite."""
    del hints
    out = [_by_itself(w) for w in words]
    for i, word in enumerate(words):
        if out[i] is Level.HARD:
            continue
        prev = words[i - 1].key if i else ""
        plain = word.key in FUNCTION_WORDS or word.key in PLAIN_NOUNS
        if prev in STRONG_CUES and not plain and not words[i - 1].ends_sentence:
            out[i] = Level.HARD
        elif prev in WEAK_CUES and _may_be_name(word):
            out[i] = Level.HARD
        elif _may_be_name(word) and not _starts_sentence(words, i):
            out[i] = Level.SOFT
    for i, word in enumerate(words):  # an initial beside a name: "D Raja", "Meera D"
        if not _initial(word.core):
            continue
        after = words[i + 1] if i + 1 < len(words) else None
        named_before = i > 0 and out[i - 1] is Level.HARD and _capitalised(words[i - 1].core)
        if after is not None and _may_be_name(after):
            out[i] = out[i + 1] = Level.HARD
        elif named_before and not words[i - 1].ends_sentence:
            out[i] = Level.HARD
    return out


def protected_words(text: str, hints: tuple[str, ...] = ()) -> list[str]:
    """The words of `text` nothing may rewrite (HARD), in order."""
    words = split_words(text)
    return [w.core for w, lv in zip(words, levels(words, hints), strict=True) if lv is Level.HARD]


def fixed_key(key: str) -> bool:
    """Is this (casefolded) word protected by itself: a digit in it, or a number, money, time or
    date word? (What `fixed_words` keeps, for a rule that only sees keys.)"""
    return any(ch.isdigit() for ch in key) or (
        key in NUMBER_WORDS or key in MONEY_WORDS or key in TIME_WORDS or key in DATE_WORDS
    )


def fixed_words(text: str) -> list[str]:
    """The words protected whatever stands beside them: numbers and anything with a digit,
    number / money / time / date words, e-mail addresses."""
    return [w.core for w in split_words(text) if _by_itself(w) is Level.HARD]


def guarded_words(text: str, hints: tuple[str, ...] = ()) -> list[str]:
    """HARD and SOFT together: what a near-match and the model may not touch."""
    words = split_words(text)
    return [w.core for w, lv in zip(words, levels(words, hints), strict=True) if lv > Level.NONE]


__all__ = [
    "ACTION_VERBS",
    "ACTION_WORDS",
    "DATE_WORDS",
    "FUNCTION_WORDS",
    "KNOWN_CAPITALS",
    "NUMBER_WORDS",
    "STRONG_CUES",
    "WEAK_CUES",
    "Level",
    "Word",
    "fixed_key",
    "fixed_words",
    "guarded_words",
    "join_words",
    "levels",
    "protected_words",
    "split_words",
]
