# src/jarvis/helpers/nudges/standup.py
"""Item 8, stand-up nudges (owner decision 1). The default meaning: stand up and move after sitting,
every N minutes inside his window, on his days. The meeting variant (built, OFF by default): ten
minutes before a calendar event whose title holds his meeting word ("stand-up"), "Your stand-up
starts in 10 minutes". Both are `nudge_standup`; the title is matched in code and never sent.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from jarvis.helpers.kinds import NudgeKind
from jarvis.helpers.nudges.calendar import CalEvent
from jarvis.helpers.nudges.models import NudgeSettings
from jarvis.helpers.nudges.schedule import due, slots
from jarvis.helpers.nudges.service import NudgeService, Plan, fixed, minute_key

KIND: NudgeKind = "nudge_standup"
MOVE_TEXT = "Time to stand up and move for a few minutes, Sir."
MEETING_TEXT = "Your stand-up starts in 10 minutes, Sir."
LEAD = timedelta(minutes=10)
_LETTERS = re.compile(r"[^a-z0-9]")


def squash(text: str) -> str:
    return _LETTERS.sub("", text.lower())


def is_meeting(event: CalEvent, word: str) -> bool:
    w = squash(word)
    return bool(w) and w in squash(event.title)


def move_plans(svc: NudgeService, s: NudgeSettings, now: datetime) -> list[Plan]:
    n = s.nudge(KIND)
    if not n.on:
        return []
    at = due(slots(KIND, n, svc.day_of(now), svc.zone), now)
    return [] if at is None else [Plan(KIND, minute_key(KIND, at), at, fixed(MOVE_TEXT))]


async def meeting_plans(svc: NudgeService, uid: str, s: NudgeSettings, now: datetime) -> list[Plan]:
    """Ten minutes before each of today's stand-up meetings (the first run at or after that)."""
    n = s.nudge(KIND)
    if not n.meeting or now.astimezone(svc.zone).weekday() not in n.days:
        return []
    events = await svc.events(uid, now)
    out = []
    for e in events or ():
        at = e.start - LEAD
        if is_meeting(e, n.word) and at <= now < e.start:
            out.append(Plan(KIND, f"{KIND}@m{e.key}", at, fixed(MEETING_TEXT)))
    return out


async def plans(svc: NudgeService, uid: str, s: NudgeSettings, now: datetime) -> list[Plan]:
    return [*move_plans(svc, s, now), *await meeting_plans(svc, uid, s, now)]


__all__ = ["KIND", "LEAD", "MEETING_TEXT", "MOVE_TEXT", "is_meeting", "plans", "squash"]
