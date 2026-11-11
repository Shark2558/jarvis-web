# src/jarvis/helpers/nudges/activity.py
"""Item 11, a nudge when a planned activity didn't happen.

A planned activity is an event in his calendar that only he wrote (`CalEvent.own`) whose title
holds one of his activity words ("walk", "gym", ...). `GRACE` after it ends, if he hasn't checked
in ("walk done", "missed my walk", "moved my walk"), JARVIS asks once:
"Your walk at 18:00 has no check-in yet, Sir. ..." (his word and the planned time only; the
event's title never goes out). Asked once: the claim is per event, so a restart or a second run
never asks again. Check-ins and the ask are kept in the sealed log (`wellbeing`), by the event's
fingerprint, never its title; with no keyring the feature is off (it keeps nothing in clear).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from jarvis.helpers.kinds import NudgeKind
from jarvis.helpers.nudges.calendar import CalEvent
from jarvis.helpers.nudges.models import NudgeSettings
from jarvis.helpers.nudges.schedule import in_window
from jarvis.helpers.nudges.service import NudgeService, Plan
from jarvis.helpers.nudges.store import Checkin, Outcome, WellDay

KIND: NudgeKind = "nudge_activity"
GRACE = timedelta(minutes=15)
LOOKBACK = timedelta(hours=2)
SOON = timedelta(minutes=30)  # a check-in may come a little before the planned start
TEXT = (
    "Your {word} at {at} has no check-in yet, Sir. Did it happen? Say '{word} done', "
    "'missed my {word}' or 'moved my {word}'."
)


def word_in(title: str, words: tuple[str, ...]) -> str | None:
    low = title.lower()
    return next((w for w in words if re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", low)), None)


def answered(day: WellDay, event: CalEvent, word: str) -> bool:
    for key in (event.key, f"w:{word}"):
        got = day.checkins.get(key)
        if got is not None and got.o != "asked":
            return True
    return False


def _hhmm(svc: NudgeService, at: datetime) -> str:
    return at.astimezone(svc.zone).strftime("%H:%M")


def _ask(svc: NudgeService, uid: str, e: CalEvent, word: str) -> Plan:
    day = svc.day_of(e.start).isoformat()

    async def words() -> str | None:
        logged = await svc.well.day(uid, day)
        if answered(logged, e, word):
            return None
        mark = Checkin(w=word, o="asked", at=_hhmm(svc, e.start))
        await svc.well.change(uid, day, lambda d: d.with_checkin(e.key, mark))
        svc.words.asked(word)  # "walk done" answers it, even if he changes his words meanwhile
        return TEXT.format(word=word, at=_hhmm(svc, e.start))

    return Plan(KIND, f"{KIND}@{e.key}", e.end + GRACE, words)


async def plans(svc: NudgeService, uid: str, s: NudgeSettings, now: datetime) -> list[Plan]:
    n = s.nudge(KIND)
    if not n.on or not n.words or not svc.well.on or not in_window(n, now, svc.zone):
        return []
    out = []
    for e in await svc.events(uid, now) or ():
        word = word_in(e.title, n.words) if e.own else None
        if word is not None and e.end + GRACE <= now <= e.end + GRACE + LOOKBACK:
            out.append(_ask(svc, uid, e, word))
    return out


async def asked_today(svc: NudgeService, uid: str, word: str) -> bool:
    """An ask about `word` today that he hasn't answered yet (the sealed log)."""
    logged = await svc.well.day(uid, svc.day_of().isoformat())
    return any(c.w == word and c.o == "asked" for c in logged.checkins.values())


async def check_in(svc: NudgeService, uid: str, word: str, outcome: Outcome) -> CalEvent | None:
    """His answer for today's latest planned `word` (or, with none found, for every one today)."""
    at = svc.now()
    today = svc.day_of(at)
    events = await svc.events(uid, at) or []
    mine = [e for e in events if e.own and word_in(e.title, (word,)) and e.start <= at + SOON]
    latest = max(mine, key=lambda e: e.start, default=None)
    key = latest.key if latest is not None else f"w:{word}"
    mark = Checkin(w=word, o=outcome, at=_hhmm(svc, latest.start) if latest else "")
    await svc.well.change(uid, today.isoformat(), lambda d: d.with_checkin(key, mark))
    return latest


__all__ = [
    "GRACE",
    "KIND",
    "LOOKBACK",
    "TEXT",
    "answered",
    "asked_today",
    "check_in",
    "plans",
    "word_in",
]
