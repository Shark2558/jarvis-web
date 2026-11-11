# src/jarvis/helpers/nudges/hydrate.py
"""Item 9, hydration reminders: "Time for a glass of water" every N minutes inside his window, on
his days (owner decision 9: every 90 min, 09:30-18:30, Monday to Saturday, OFF until he switches it
on). His water log (`log_water`) is sealed (`wellbeing`): with no keyring the log is off, while the
reminders still work. A count is never put in a message or a log line.
"""

from __future__ import annotations

from datetime import datetime

from jarvis.helpers.kinds import NudgeKind
from jarvis.helpers.nudges.models import NudgeSettings
from jarvis.helpers.nudges.schedule import due, slots
from jarvis.helpers.nudges.service import NudgeService, Plan, fixed, minute_key
from jarvis.helpers.nudges.store import WellDay

KIND: NudgeKind = "nudge_hydrate"
TEXT = "Time for a glass of water, Sir."


def plans(svc: NudgeService, s: NudgeSettings, now: datetime) -> list[Plan]:
    n = s.nudge(KIND)
    if not n.on:
        return []
    at = due(slots(KIND, n, svc.day_of(now), svc.zone), now)
    return [] if at is None else [Plan(KIND, minute_key(KIND, at), at, fixed(TEXT))]


async def log_water(svc: NudgeService, uid: str, glasses: int) -> WellDay:
    day = svc.day_of().isoformat()
    return await svc.well.change(uid, day, lambda d: d.plus_water(glasses))


async def log_stood(svc: NudgeService, uid: str) -> WellDay:
    day = svc.day_of().isoformat()
    return await svc.well.change(uid, day, lambda d: d.plus_stood(1))


__all__ = ["KIND", "TEXT", "log_stood", "log_water", "plans"]
