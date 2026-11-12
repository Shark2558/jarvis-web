# src/jarvis/helpers/nudges/phrases.py
"""Part C's No-AI phrases (plan D18): fixed, anchored patterns (the whole message) that end in Part
C's own tools through the gateway, so every Part C feature works with the AI off. They are tried
before every older pattern, so "don't remind me to stand up" stops the nudge and never sets a
reminder, and "remind me to drink water every 45 minutes" changes the water nudge (a one-off
"remind me to drink water at 5 pm" still falls through to the reminders). Conservative: anything
else is left for the other routers. Telegram replies ("stop water") reach the same rules.

A check-in ("walk done", "missed my gym") fires only when its word is one of his activity words
or answers a check-in ask JARVIS sent in the last `ASK_OPEN`; "homework done" or "I missed my
flight" fall through. The router is synchronous, so `CheckinWords` keeps those words in memory:
his words from the last read of his settings (every clock run reads them), his default words until
then. A bare "snooze" means the nudge sent last (`nudge_snooze` with kind `last`).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Mapping
from datetime import datetime, timedelta
from types import MappingProxyType

from jarvis.helpers.nudges.models import DEFAULTS, NudgeSettings
from jarvis.offline.rules import NoAICall, NoAIRoute

MAX_TEXT = 200
CHECKIN = "nudge_activity_checkin"
LAST = "last"  # `nudge_snooze`'s kind for a bare "snooze": the nudge sent most recently
ASK_OPEN = timedelta(hours=12)  # a check-in ask stays answerable this long
DEFAULT_WORDS: frozenset[str] = frozenset(DEFAULTS["nudge_activity"].words)
_LEAD = r"^(?:jarvis[,\s]+)?(?:please\s+)?"
_END = r"(?:\s+please)?\s*[.!?]*$"
_KINDS = (
    r"stand[\s-]?ups?|standing(?:\s+up)?|water|hydration|drink(?:ing)?(?:\s+water)?|"
    r"activit(?:y|ies)|walk\s+check(?:-?ins?)?|free[\s-]?time(?:\s+ideas?)?|focus|"
    r"top\s+priority|priority"
)
_ACTS = r"stand\s+up(?:\s+and\s+move)?|move|drink\s+(?:some\s+)?water|have\s+(?:some\s+)?water"
K = rf"(?P<k>{_KINDS})(?:\s+(?:nudges?|reminders?|alerts?))?"
K_ACT = rf"(?P<k>{_ACTS}|{_KINDS})(?:\s+(?:nudges?|reminders?|alerts?))?"
ALLN = r"(?:all\s+(?:the\s+)?|the\s+|my\s+)?(?:nudges?|reminders)"
TODAY = r"(?:\s+(?:for\s+)?(?:today|the\s+rest\s+of\s+(?:the\s+)?day))?"
GOOD = r"(?P<good>\s+(?:for\s+good|altogether|permanently|forever))?"
DUR = r"(?:(?P<n>\d{1,3}|an?|one|two|three|half\s+an?)\s*)?(?P<u>minutes?|mins?|hours?|hrs?)"
WORD = r"(?P<w>[a-z][a-z\-]{1,20}(?:\s[a-z][a-z\-]{1,20})?)"
_NUMBER = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3}

Build = Callable[[re.Match[str]], NoAIRoute]
Known = Callable[[], Collection[str]]
Router = Callable[[str, datetime], NoAIRoute | None]


class CheckinWords:
    """The activity words a check-in phrase may name: each owner's words from the last read or
    change of his settings (`saw`), his default words before any, plus the words of check-in asks
    sent in the last `ASK_OPEN` (`asked`). Replaced, never changed in place."""

    def __init__(self, now: Callable[[], datetime]) -> None:
        self._now = now
        self._his: Mapping[str, frozenset[str]] = MappingProxyType({})
        self._asked: Mapping[str, datetime] = MappingProxyType({})

    def saw(self, uid: str, settings: NudgeSettings) -> None:
        words = frozenset(settings.nudge("nudge_activity").words)
        self._his = MappingProxyType({**self._his, uid: words})

    def asked(self, word: str) -> None:
        self._asked = MappingProxyType({**self._asked, word: self._now()})

    def __call__(self) -> frozenset[str]:
        his = frozenset().union(*self._his.values()) if self._his else DEFAULT_WORDS
        since = self._now() - ASK_OPEN
        return his | {w for w, at in self._asked.items() if at >= since}


def _one(tool: str, **args: str) -> NoAIRoute:
    return NoAIRoute((NoAICall(tool, dict(args)),))


def _group(m: re.Match[str], name: str) -> str:
    got = m.groupdict().get(name)
    return got or ""


def kind_word(said: str) -> str:
    low = " ".join(said.lower().replace("-", " ").split())
    if not low:
        return "all"
    if low.startswith(("stand", "move")):
        return "standup"
    if low.startswith(("water", "hydra", "drink", "have")):
        return "water"
    if low.startswith(("activit", "walk")):
        return "activity"
    if low.startswith("free"):
        return "free_time"
    return "focus"


def _amount(word: str) -> float:
    w = word.lower()
    if w.startswith("half"):
        return 0.5
    return float(w) if w.isdigit() else float(_NUMBER.get(w, 1))


def minutes(amount: str, unit: str) -> str:
    a = _amount(amount)
    return str(int(a * 60) if unit.lower().startswith("h") else int(a))


def _stop(m: re.Match[str]) -> NoAIRoute:
    kind = kind_word(_group(m, "k"))
    return _one("nudge_stop", kind=kind, **({"for_good": "true"} if _group(m, "good") else {}))


def _snooze(m: re.Match[str]) -> NoAIRoute:
    said = _group(m, "k")
    kind = kind_word(said) if said else ("all" if _group(m, "all") else LAST)
    if _group(m, "tomorrow"):
        return _one("nudge_snooze", kind=kind, until="tomorrow")
    n, u = _group(m, "n"), _group(m, "u")
    return _one("nudge_snooze", kind=kind, minutes=minutes(n, u) if u else "60")


def _switch(m: re.Match[str]) -> NoAIRoute:
    on = "true" if m["o"].lower() == "on" else "false"
    return _one("nudge_set", kind=kind_word(m["k"]), on=on)


def _every(m: re.Match[str]) -> NoAIRoute:
    every = minutes(_group(m, "n"), m["u"])
    return _one("nudge_set", kind=kind_word(m["k"]), on="true", every_minutes=every)


def _glasses(m: re.Match[str]) -> NoAIRoute:
    n = _group(m, "n").lower()
    count = n if n.isdigit() else str(_NUMBER.get(n, 1))
    return _one("nudge_water_log", glasses=count)


def _add_idea(m: re.Match[str]) -> NoAIRoute:
    args = {"text": m["t"].strip(" ,.-:")}
    if _group(m, "n"):
        args["minutes"] = m["n"]
    place = _group(m, "p").lower()
    if place:
        args["place"] = {"inside": "indoor", "outside": "outdoor"}.get(place, place)
    return _one("freetime_add", **args)


def _suggest(m: re.Match[str]) -> NoAIRoute:
    n = _group(m, "n")
    return _one("freetime_suggest", **({"minutes": n} if n else {}))


def _checkin(outcome: str) -> Build:
    return lambda m: _one(CHECKIN, word=m["w"].lower(), outcome=outcome)


_FREE = r"free[\s-]?time"
_RULES: tuple[tuple[str, Build], ...] = (
    # the stand-up meeting variant (owner decision 1): on and off
    (
        r"(?:remind|tell|nudge)\s+me\s+(?:10\s+minutes\s+)?before\s+(?:my|the)\s+stand[\s-]?up"
        r"(?:\s+meetings?)?",
        lambda m: _one("nudge_set", kind="standup", meeting="true"),
    ),
    (
        r"(?:stop\s+reminding|don'?t\s+remind|do\s+not\s+remind)\s+me\s+(?:before|about)\s+"
        r"(?:my|the)\s+stand[\s-]?up\s+meetings?",
        lambda m: _one("nudge_set", kind="standup", meeting="false"),
    ),
    # stop: every nudge, or one; for today unless "for good"
    (rf"(?:no\s+more|stop|pause|mute|no)\s+{ALLN}{TODAY}{GOOD}", _stop),
    (rf"stop\s+nudging\s+me{TODAY}{GOOD}", _stop),
    (rf"(?:stop|mute|pause|silence|no\s+more)\s+(?:the\s+)?{K}{TODAY}{GOOD}", _stop),
    (
        rf"(?:don'?t|do\s+not|stop|never)\s+(?:remind(?:ing)?|nudg(?:e|ing))\s+me\s+(?:to|about)\s+"
        rf"{K_ACT}{TODAY}{GOOD}",
        _stop,
    ),
    # snooze and resume
    (
        rf"snooze(?:\s+(?:the\s+)?(?:{K}|(?P<all>{ALLN})))?(?:\s+for\s+{DUR}|\s+(?:until|till)\s+"
        r"(?P<tomorrow>tomorrow))?",
        _snooze,
    ),
    (
        rf"(?:resume|unsnooze|unpause|restart)\s+(?:the\s+)?(?:{K}|{ALLN})",
        lambda m: _one("nudge_resume", kind=kind_word(_group(m, "k"))),
    ),
    # switch on / off, and how often
    (rf"(?:turn|switch)\s+(?P<o>on|off)\s+(?:the\s+)?{K}", _switch),
    (rf"(?:turn|switch)\s+(?:the\s+)?{K}\s+(?P<o>on|off)", _switch),
    (rf"(?:remind|nudge)\s+me\s+to\s+(?P<k>{_ACTS})\s+every\s+{DUR}", _every),
    # what is on, and today's log
    (
        r"(?:show|list)\s+(?:me\s+)?my\s+nudges|(?:what|which)\s+nudges\s+are\s+on|nudge\s+status"
        r"|how\s+much\s+water\s+(?:have\s+i\s+had|did\s+i\s+drink)(?:\s+today)?"
        r"|how\s+many\s+(?:glasses\s+of\s+water|stand[\s-]?ups)(?:\s+have\s+i\s+(?:had|done))?"
        r"(?:\s+today)?",
        lambda m: _one("nudge_status"),
    ),
    (
        r"(?:i\s+)?(?:had|drank|drunk|finished)\s+(?:(?P<n>a|an|one|two|three|\d{1,2})\s+)?"
        r"(?:glass(?:es)?\s+of\s+)?water|(?:log|add)\s+(?:a\s+|one\s+)?(?:glass\s+of\s+)?water"
        r"|water\s+done",
        _glasses,
    ),
    (
        r"(?:i\s+)?(?:have\s+)?stood\s+up(?:\s+and\s+moved)?|(?:log|add)\s+a\s+stand[\s-]?up"
        r"|stand[\s-]?up\s+done",
        lambda m: _one("nudge_standup_log"),
    ),
    # free time (item 12)
    (
        rf"what\s+(?:can|should|could)\s+i\s+do\s+(?:with|in)\s+(?:my\s+|this\s+)?free\s+time"
        rf"|suggest\s+something\s+(?:to\s+do|for\s+my\s+free\s+time)"
        rf"|(?:give\s+me\s+)?an?\s+{_FREE}\s+idea"
        r"|i'?m\s+free,?\s+what\s+(?:can|should)\s+i\s+do(?:\s+now)?",
        _suggest,
    ),
    (
        r"i\s+have\s+(?P<n>\d{1,3})\s+(?:minutes|mins)(?:\s+free)?,?\s+what\s+(?:can|should)\s+i"
        r"\s+do(?:\s+now)?",
        _suggest,
    ),
    (
        rf"(?:show|list|read)\s+(?:me\s+)?my\s+{_FREE}\s+(?:list|ideas)"
        rf"|what'?s\s+on\s+my\s+{_FREE}\s+list",
        lambda m: _one("freetime_list"),
    ),
    (
        rf"add\s+(?:an?\s+idea\s+)?to\s+my\s+{_FREE}\s+list\s*[:,-]?\s*(?P<t>[^\n]{{1,80}}?)"
        r"(?:[,\s]+(?P<n>\d{1,3})\s*(?:minutes|mins?))?"
        r"(?:[,\s]+(?P<p>indoor|outdoor|inside|outside|any))?",
        _add_idea,
    ),
    (
        rf"(?:remove|delete|take)\s+(?P<t>[^\n]{{1,80}}?)\s+(?:from|off)\s+my\s+{_FREE}\s+list",
        lambda m: _one("freetime_remove", text=m["t"].strip()),
    ),
    (
        rf"(?:i\s+)?did\s+(?P<t>[^\n]{{1,80}}?)\s+from\s+my\s+(?:{_FREE}\s+)?list",
        lambda m: _one("freetime_done", text=m["t"].strip()),
    ),
    # a planned activity's check-in (item 11): only his activity words (`_his`); the tool checks too
    (rf"(?:i\s+)?(?:did|finished|completed|went\s+for|went\s+on)\s+my\s+{WORD}", _checkin("done")),
    (rf"(?:my\s+)?{WORD}\s+(?:is\s+)?(?:done|happened|complete)", _checkin("done")),
    (rf"(?:i\s+)?(?:missed|skipped)\s+my\s+{WORD}(?:\s+today)?", _checkin("missed")),
    (rf"(?:i\s+)?(?:moved|postponed|rescheduled)\s+my\s+{WORD}", _checkin("moved")),
)
_COMPILED = tuple(
    (re.compile(_LEAD + f"(?:{body})" + _END, re.IGNORECASE), fn) for body, fn in _RULES
)


def _his(got: NoAIRoute, known: Known) -> bool:
    """A check-in names one of his activity words (or a pending ask's); every other call passes."""
    call = got.calls[0]
    return call.tool != CHECKIN or call.arguments["word"] in known()


def _defaults() -> frozenset[str]:
    return DEFAULT_WORDS


def route(text: str, now: datetime, known: Known = _defaults) -> NoAIRoute | None:
    """The first matching rule's tool call, or None (left to the other routers)."""
    one = " ".join(text.split())
    if not one or len(one) > MAX_TEXT:
        return None
    for pattern, build in _COMPILED:
        m = pattern.match(one)
        if m is not None and _his(got := build(m), known):
            return got
    return None


def phrasebook(known: Known) -> Router:
    """The part's router: the check-in phrases follow `known` (his words, kept by the service)."""

    def routed(text: str, now: datetime) -> NoAIRoute | None:
        return route(text, now, known)

    return routed


PHRASES: tuple[Router, ...] = (route,)

__all__ = [
    "ASK_OPEN",
    "DEFAULT_WORDS",
    "LAST",
    "PHRASES",
    "CheckinWords",
    "kind_word",
    "minutes",
    "phrasebook",
    "route",
]
