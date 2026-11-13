# src/jarvis/understand/context.py
"""Where each fixed rule of "heard / understood as" may fire (R11.1; plan D8, D21-B; code review
H1). Plain code and word sets: no model, no network.

A rule names the exact heard words and what they become (`jarvis.understand.rules.RULES`); its
`when` is one of the checks here, given a `Ctx` (the words written so far, the heard words
still to come, the hints). A rule that could turn one real word into another real word
("remainder" -> "reminder", "colander" -> "calendar", "male" -> "mail", "power point" ->
"PowerPoint", "D" -> "the", "ad" -> "add", "javis" -> "JARVIS") fires only on a cue that makes the
meant word certain, and never beside the words that say the heard one was right: money talk
for "remainder", the kitchen for "colander", the home's sockets for "power point", shopping for
an XL sheet, a letter that labels a thing for "D", a person the request is sent to for
"javis". Otherwise the word is left as heard. The audit of every rule is in INTEGRATION-B 5a.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from jarvis.understand.words import (
    FUNCTION_WORDS,
    STRONG_CUES,
    WEAK_CUES,
    Level,
    Word,
    fixed_key,
)

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


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


# "remainder" is the amount left: with any of these in the sentence it is never a reminder
MONEY_TALK = _words(
    "pay paid paying pays payment transfer transferred transferring send sent sending deposit "
    "withdraw withdrew owe owed owes owing refund lend lent borrow borrowed split balance amount "
    "account accounts savings saving bank loan emi due dues bill bills money cash credit debit "
    "left remaining divide divided division rupee rupees rs inr salary rent fee fees invoice"
)
# what a reminder is set, added or made with: "set a remainder", "new remainder"
REMINDER_MAKERS = _words("set add create new another make schedule put")
# a reminder TO do something: "remainder to call Meera"
REMINDER_DOINGS = _words(
    "call ring phone text message mail email send pay check take buy book submit renew drink "
    "stretch walk meet ask tell remind leave go start stop water feed pick collect"
)
# "remainders": the owner's own list of them
REMINDERS_SHOWN = _words("show list set clear upcoming pending")
REMINDERS_LOOKS = _words("show list check read clear see open")
# a calendar, as opposed to a kitchen colander
CALENDAR_TALK = _words(
    "event events meeting meetings appointment appointments schedule scheduled session sessions "
    "reminder reminders invite invites booked free busy slot slots add put block plan"
)
KITCHEN_TALK = _words(
    "wash washed rinse rinsed drain drained strain strained pasta rice noodles vegetables veg "
    "kitchen sink dishwasher steel plastic pot pan sieve cook cooking boil boiled recipe dal "
    "water fruit fruits buy order"
)
# a wall socket ("switch off the power point"), as opposed to a deck
HOME_TALK = _words(
    "switch switched turn turned plug plugged unplug socket sockets light lights fan fans "
    "charger charging charge wall off electrician electric electrical spark sparking voltage "
    "wire wiring fuse bulb appliance ac heater geyser iron inverter mcb hall bedroom room"
)
# an XL bed sheet, as opposed to an Excel one
SHOPPING_TALK = _words(
    "buy bought order ordered cart size bed cotton king queen single double linen mattress "
    "pillow amazon flipkart shop store price"
)
# "fail" as a verb: "why did the csv fail", "will the pdf fail"
VERB_FAIL = _words(
    "did does do didn't doesn't don't will would could can may might should shall won't can't "
    "couldn't wouldn't why if when not never to"
)
# a letter that labels a thing: "D drive", "D block", "vitamin D", "D column"
LABEL_NOUNS = _words(
    "block blocks wing drive section grade class type category division ward floor sector phase "
    "tower building gate plan team batch group level size cup major minor flat sharp rank form "
    "series model version unit zone line road street cross stage vitamin company squad row rows "
    "column columns cell cells sheet tab key"
)
# "mail" as the thing sent or read: the word after it
AFTER_A_THING = _words(
    "to from for about and or with on in please now today tomorrow regarding saying that again"
)
# being spoken to: "hey jarviz", "thank you javis"
CALLING = _words("hey hi hello ok okay oh yo thanks please dear")
# where an "ad" starts a request: "please ad this", "can you ad it"
REQUEST_OPENERS = _words("please jarvis sir also")
ASKING = _words("can could will would")
# WhatsApp as the app: "on what's app", "a what sap message"
APP_BEFORE = _words("on via by through my open send check use")
APP_AFTER = _words("message messages msg chat chats group groups call calls number draft status")


@dataclass(frozen=True)
class Ctx:
    """What a rule may look at: the words already written (after earlier rules), the heard
    words still to come, and the hints."""

    before: tuple[str, ...]  # keys of the output so far
    after: tuple[Word, ...]  # heard words after the match
    after_levels: tuple[Level, ...]
    hints: frozenset[str]  # every hint word, casefolded
    tail: str = ""  # the punctuation after the matched words ("," "." ...)

    @property
    def prev(self) -> str:
        return self.before[-1] if self.before else ""

    @property
    def prev2(self) -> str:
        return self.before[-2] if len(self.before) > 1 else ""

    @property
    def next(self) -> str:
        return self.after[0].key if self.after else ""

    @property
    def next2(self) -> str:
        return self.after[1].key if len(self.after) > 1 else ""

    def says(self, words: frozenset[str]) -> bool:
        """Does any word of the sentence (before or after the match) belong to `words`?"""
        return any(k in words for k in self.before) or any(w.key in words for w in self.after)


When = Callable[[Ctx], bool]


def file_next(c: Ctx) -> bool:
    return c.next in FILE_WORDS


def csv_context(c: Ctx) -> bool:
    """CSV: a file word follows, or a CSV is waiting or attached and nobody talks money (a
    bank's or a payee's initials are never a file type)."""
    return c.next in FILE_WORDS or ("csv" in c.hints and not c.says(MONEY_TALK))


def after_file_type(c: Ctx) -> bool:
    """ "fail" is "file" after a file type, never the verb ("why did the csv fail")."""
    return c.prev in FILE_TYPES and c.next not in VERB_FAIL and not c.says(VERB_FAIL)


def power_point(c: Ctx) -> bool:
    return not c.says(HOME_TALK)  # "switch off the power point" is a wall socket


def xl_sheet(c: Ctx) -> bool:
    return not c.says(SHOPPING_TALK)  # "an XL bed sheet" is a size


def calendar_slot(c: Ctx) -> bool:
    """ "colander" is "calendar": after "my" / "google", or after "the / to / in / on" when the
    sentence is about the calendar; never in the kitchen."""
    if c.says(KITCHEN_TALK):
        return False
    if c.prev in {"my", "google"}:
        return True
    timed = any(fixed_key(k) for k in c.before) or any(fixed_key(w.key) for w in c.after)
    return c.prev in {"the", "to", "in", "on"} and (timed or c.says(CALENDAR_TALK))


def thing_follows(c: Ctx) -> bool:
    """ "D" is "the": a plain word follows that a letter does not label ("D drive", "D block",
    "vitamin D"), and what came before is no person and no "the"."""
    if not c.after or c.after_levels[0] is Level.HARD:
        return False
    nxt = c.after[0]
    plain = nxt.core.isalpha() and nxt.key not in FUNCTION_WORDS and nxt.key not in LABEL_NOUNS
    named = len(nxt.core) > 1 and nxt.core[0].isupper() and not nxt.core.isupper()
    known_before = not c.before or c.prev in FUNCTION_WORDS or c.prev in COMMON_VERBS
    return plain and not named and known_before and c.prev not in DETERMINERS


def determiner_follows(c: Ctx) -> bool:
    return c.next in DETERMINERS


def to_slot(c: Ctx) -> bool:
    """ "Tu" is "to": a determiner follows and the word before takes no person."""
    return c.next in DETERMINERS and c.prev not in STRONG_CUES and c.prev not in WEAK_CUES


def number_for_to(c: Ctx) -> bool:
    return bool(c.before) and c.next in DETERMINERS and c.prev not in {"add", "the", "all"}


def add_slot(c: Ctx) -> bool:
    """ "ad" is "add" only where a request starts ("please ad this", "can you ad it"), never
    in the middle of a list of things ("the banner and ad the client liked")."""
    opens = (
        not c.before
        or c.prev in REQUEST_OPENERS
        or (c.prev == "then" and c.prev2 in {"", "and"})
        or (c.prev == "you" and c.prev2 in ASKING)
    )
    return opens and c.next in {
        *("this", "that", "these", "those", "it", "the", "a", "an", "my", "d", "them", "all"),
        "both",
    }


def called(c: Ctx) -> bool:
    """JARVIS only when spoken to ("hey jarviz", "thank you javis", a sentence that starts with
    it); a "javis" the request is sent to is a person."""
    return not c.before or c.prev in CALLING or (c.prev == "you" and c.prev2 == "thank")


def for_a_time(c: Ctx) -> bool:
    """A time or a date right after, or "for / at / on / by" one."""
    if fixed_key(c.next):
        return True
    return c.next in {"for", "at", "on", "by"} and fixed_key(c.next2)


def reminder_slot(c: Ctx) -> bool:
    """ "remainder" is "reminder" only on a real reminder cue: "set / add / create / new (a)
    remainder" always; "remainder for 7 pm", "remainder to call ..." or "remind" only when no
    money is talked about ("pay the remainder" is the amount left)."""
    if c.prev in {"set", "add", "create", "new", "another"}:
        return True
    if c.prev in {"a", "an", "one"} and c.prev2 in REMINDER_MAKERS:
        return True
    if c.says(MONEY_TALK):
        return False
    doing = c.next == "to" and c.next2 in REMINDER_DOINGS
    return for_a_time(c) or doing or c.says(frozenset({"remind"}))


def reminders_slot(c: Ctx) -> bool:
    """ "remainders" is "reminders": the owner's own list ("show my remainders", "any
    remainders today"), never amounts ("transfer all remainders to savings")."""
    if c.says(MONEY_TALK) or c.next == "of":
        return False
    if c.prev in REMINDERS_SHOWN:
        return True
    looked = c.prev in {"my", "the", "all", "any"} and c.prev2 in REMINDERS_LOOKS
    return looked or for_a_time(c)


def mail_slot(c: Ctx) -> bool:
    """ "male" is "mail" only as the thing sent or read ("send a male to the office", "check my
    male"), never as a word about someone ("a male nurse", "the male ward")."""
    if c.next and c.next not in AFTER_A_THING and not c.tail:
        return False
    if c.prev in MAIL_VERBS or c.prev == "unread":
        return True
    return c.prev in {"a", "an", "the", "my", "new", "this"} and c.prev2 in MAIL_VERBS


def the_app(c: Ctx) -> bool:
    return c.prev in APP_BEFORE or c.next in APP_AFTER or c.prev in DETERMINERS


__all__ = [
    "COMMON_VERBS",
    "Ctx",
    "DETERMINERS",
    "FILE_TYPES",
    "FILE_WORDS",
    "MAIL_VERBS",
    "When",
    "add_slot",
    "after_file_type",
    "calendar_slot",
    "called",
    "csv_context",
    "determiner_follows",
    "file_next",
    "for_a_time",
    "mail_slot",
    "number_for_to",
    "power_point",
    "reminder_slot",
    "reminders_slot",
    "the_app",
    "thing_follows",
    "to_slot",
    "xl_sheet",
]
