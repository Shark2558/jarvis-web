# src/jarvis/watch/phrases.py
"""Part D's No-AI phrases (docs/plans/r7-mobile.md D18; R11 D18's rules): fixed, anchored patterns
that answer with Part D's own tools through the gateway, with the AI off too. The whole message
must be the phrase (an optional "Jarvis," and "please", end punctuation), so "how did I sleep
through the meeting" or "remind me to sleep at 11" are never taken here.

- "how did I sleep (last night)", "how was my sleep" -> `sleep_last_night`
- "how did I sleep this week", "my sleep this week" -> `sleep_week`
- "steps today", "how many steps today", "what's my heart rate today" -> `watch_today`
- "I slept 11:30 to 6" (his own words) -> `sleep_note` {start "23:30", end "06:00"}: a bare hour
  of 7 to 11 for the start is the evening, 1 to 6 the small hours, 12 midnight; for the end every
  bare hour is the morning (12 is noon); am / pm and a two-digit 24-hour time say it themselves
- "sos status", "who are my emergency contacts" -> `sos_status` (a read: no phrase ever sends)
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from jarvis.offline.rules import NoAICall, NoAIRoute

_I = re.IGNORECASE
_LEAD = r"^(?:(?:hey|ok|okay)\s+)?(?:jarvis[,\s]+)?(?:please\s+)?"
_END = r"(?:\s+please)?[\s.!?]*$"
_NIGHT = r"(?:\s+last\s+night)?"


def _p(body: str) -> re.Pattern[str]:
    return re.compile(_LEAD + r"(?:" + body + r")" + _END, _I)


LAST = _p(
    r"how\s+(?:did|do)\s+i\s+sleep" + _NIGHT
    + r"|how\s+(?:well|long)\s+did\s+i\s+sleep" + _NIGHT
    + r"|how\s+was\s+my\s+sleep" + _NIGHT
    + r"|(?:show\s+(?:me\s+)?)?my\s+sleep" + _NIGHT
    + r"|last\s+night'?s\s+sleep|sleep\s+last\s+night"
)  # fmt: skip
_WEEK = r"(?:this\s+week|(?:over|for)\s+the\s+last\s+(?:7|seven)\s+(?:days|nights))"
WEEK = _p(
    r"how\s+(?:did\s+i\s+sleep|have\s+i\s+(?:slept|been\s+sleeping))\s+" + _WEEK
    + r"|how\s+was\s+my\s+sleep\s+" + _WEEK
    + r"|(?:show\s+(?:me\s+)?)?my\s+sleep\s+" + _WEEK
    + r"|sleep\s+" + _WEEK
)  # fmt: skip
_SO_FAR = r"(?:\s+(?:today|so\s+far(?:\s+today)?))?"
TODAY = _p(
    r"(?:my\s+)?steps" + _SO_FAR
    + r"|how\s+many\s+steps(?:\s+(?:have|did)\s+i\s+(?:taken|take|walked|walk|done|do))?"
    + _SO_FAR
    + r"|(?:what(?:'s|\s+is)\s+)?my\s+heart\s+rate" + _SO_FAR
    + r"|heart\s+rate\s+today|(?:my\s+)?watch\s+today"
)  # fmt: skip
_TIME = r"(\d{1,2})(?:[:.](\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?"
NOTE = _p(r"i\s+slept\s+(?:from\s+)?" + _TIME + r"\s*(?:to|till|until|-)\s*" + _TIME)
SOS = _p(
    r"(?:my\s+)?sos(?:\s+(?:status|set\s*up))?"
    r"|who\s+are\s+my\s+emergency\s+contacts"
    r"|(?:my\s+)?emergency\s+(?:contacts|sos)(?:\s+status)?"
)

Role = Literal["start", "end"]


def clock(hour: str, minute: str | None, meridiem: str | None, role: Role) -> str | None:
    """His spoken time as "HH:MM", or None when it is no time of day."""
    h, m = int(hour), int(minute or 0)
    if h > 23 or m > 59:
        return None
    mer = (meridiem or "").replace(".", "").lower()
    if mer:
        if not 1 <= h <= 12:
            return None
        h = h % 12 + (12 if mer == "pm" else 0)
    elif (len(hour) == 2 and hour.startswith("0")) or h == 0 or h >= 13:
        pass  # a 24-hour time says itself
    elif role == "start":
        h = 0 if h == 12 else (h + 12 if h >= 7 else h)
    return f"{h:02d}:{m:02d}"


def _one(tool: str, **args: str) -> NoAIRoute:
    return NoAIRoute((NoAICall(tool, dict(args)),))


def watch_phrases(text: str, now: datetime) -> NoAIRoute | None:
    """The tool call for one of Part D's phrases, or None (not ours)."""
    del now
    t = " ".join(text.split())
    if WEEK.match(t):
        return _one("sleep_week")
    if LAST.match(t):
        return _one("sleep_last_night")
    if TODAY.match(t):
        return _one("watch_today")
    if SOS.match(t):
        return _one("sos_status")
    m = NOTE.match(t)
    if m is not None:
        start = clock(m[1], m[2], m[3], "start")
        end = clock(m[4], m[5], m[6], "end")
        if start is not None and end is not None:
            return _one("sleep_note", start=start, end=end)
    return None


__all__ = ["LAST", "NOTE", "SOS", "TODAY", "WEEK", "clock", "watch_phrases"]
