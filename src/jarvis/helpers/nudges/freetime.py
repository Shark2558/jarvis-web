# src/jarvis/helpers/nudges/freetime.py
"""Item 12, free-time suggestions from his own list: plain code, no model (D1, D12).

`gap_minutes`: from now to his next event (any event: busy is busy), never past the window's end;
inside an event there is no gap. `pick`: an idea from his list that fits the gap, wasn't done in
the last `RECENT_DAYS` days, and is not an outdoor one when rain is likely (Part B's weather; None =
unknown, no rule). Among the ideas that qualify the day decides which (so it varies, and the same
day gives the same answer). At his times (OFF by default) the nudge offers it; with no gap or no
idea that fits, nothing is sent. His calendar not linked: no nudge (JARVIS can't tell he is
free); `suggest` (the tool) then uses the minutes he gives.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from jarvis.helpers.kinds import NudgeKind
from jarvis.helpers.nudges.calendar import CalEvent
from jarvis.helpers.nudges.models import Idea, NudgeSettings
from jarvis.helpers.nudges.schedule import at_local, due, slots
from jarvis.helpers.nudges.service import NotNow, NudgeService, Plan, minute_key

KIND: NudgeKind = "nudge_free_time"
TEXT = "You look free for {gap}, Sir. From your list: {idea} ({minutes} min)."
RECENT_DAYS = 3
MIN_GAP = 15


def gap_minutes(events: list[CalEvent], now: datetime, until: datetime) -> int:
    if any(e.start <= now < e.end for e in events):
        return 0
    nxt = min((e.start for e in events if e.start > now), default=until)
    return max(0, int((min(nxt, until) - now).total_seconds() // 60))


def recent(idea: Idea, today: date) -> bool:
    if idea.last_done is None:
        return False
    return (today - date.fromisoformat(idea.last_done)).days < RECENT_DAYS


def pick(ideas: tuple[Idea, ...], gap: int, rain: bool | None, today: date) -> Idea | None:
    fits = [
        i
        for i in ideas
        if i.minutes <= gap and not recent(i, today) and not (rain and i.place == "outdoor")
    ]
    return fits[today.toordinal() % len(fits)] if fits else None


def say_gap(minutes: int) -> str:
    """Spoken to the nearest 5 minutes ("about an hour and 30 minutes")."""
    minutes = max(5, 5 * round(minutes / 5))
    hours, rest = divmod(minutes, 60)
    if not hours:
        return f"about {minutes} minutes"
    whole = "an hour" if hours == 1 else f"{hours} hours"
    return f"about {whole}" if rest < 10 else f"about {whole} and {rest} minutes"


def say(idea: Idea, gap: int) -> str:
    return TEXT.format(gap=say_gap(gap), idea=idea.text, minutes=idea.minutes)


async def suggest(
    svc: NudgeService, uid: str, s: NudgeSettings, now: datetime, minutes: int | None
) -> tuple[Idea | None, int | None]:
    """The pick for now and the gap it used (None: no calendar and no minutes given)."""
    n = s.nudge(KIND)
    until = at_local(svc.day_of(now), n.end, svc.zone)
    if minutes is not None:
        gap: int | None = minutes
    else:
        events = await svc.events(uid, now)
        gap = None if events is None else gap_minutes(events, now, max(until, now))
    if gap is None or gap < MIN_GAP:
        return None, gap
    rain = await svc.rain_likely(uid, now, now + timedelta(minutes=gap))
    return pick(s.ideas, gap, rain, svc.day_of(now)), gap


def plans(svc: NudgeService, uid: str, s: NudgeSettings, now: datetime) -> list[Plan]:
    n = s.nudge(KIND)
    if not n.on or not s.ideas or not svc.agenda.linked:
        return []
    at = due(slots(KIND, n, svc.day_of(now), svc.zone), now)
    if at is None:
        return []

    async def words() -> str | None:
        idea, gap = await suggest(svc, uid, s, now, None)
        if gap is None:
            raise NotNow("the calendar didn't answer")
        return say(idea, gap) if idea is not None else None

    return [Plan(KIND, minute_key(KIND, at), at, words)]


__all__ = ["KIND", "MIN_GAP", "RECENT_DAYS", "gap_minutes", "pick", "plans", "say", "suggest"]
