# src/jarvis/brief/family_day.py
"""The brief's "Family today" section (R1 D15): what each registered family calendar holds today.

Read-only, no model, never part of the AI-summary input. Absent (None) until the owner has added a
member. A member who shared free/busy only shows busy blocks; one whose calendar Google won't show
any more is marked unavailable. Titles are other people's words: one clean line here, defanged and
quoted by `brief.render` like every other title. Fails on its own (the service handles errors).
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from jarvis.brief.models import FamilyEvent, FamilyMemberDay, FamilySection
from jarvis.family.models import Member
from jarvis.family.service import FamilyService
from jarvis.tools.card import one_line

TITLE_LIMIT = 80
MAX_PER_MEMBER = 6


def _clock(value: Any, tz: tzinfo) -> tuple[str, bool]:
    """('09:30', False) for a timed value, ('', True) for an all-day date."""
    if isinstance(value, dict) and value.get("dateTime"):
        try:
            dt = datetime.fromisoformat(str(value["dateTime"]).replace("Z", "+00:00"))
            return dt.astimezone(tz).strftime("%H:%M"), False
        except ValueError:
            return "", False
    return "", True


def event_lines(events: list[dict[str, Any]], tz: tzinfo) -> tuple[FamilyEvent, ...]:
    out = []
    for e in events:
        when, all_day = _clock(e.get("start"), tz)
        title = one_line(e.get("summary"), TITLE_LIMIT) or "(no title)"
        out.append(FamilyEvent(when="All day" if all_day else when, title=title))
    return tuple(out[:MAX_PER_MEMBER])


def busy_lines(blocks: list[tuple[datetime, datetime]], tz: tzinfo) -> tuple[FamilyEvent, ...]:
    return tuple(
        FamilyEvent(when=f"{s.astimezone(tz):%H:%M}–{e.astimezone(tz):%H:%M}")
        for s, e in blocks[:MAX_PER_MEMBER]
    )


class FamilyBrief:
    def __init__(self, svc: FamilyService) -> None:
        self._svc = svc

    async def _one(
        self, uid: str, m: Member, start: datetime, end: datetime, tz: ZoneInfo
    ) -> FamilyMemberDay:
        got = await self._svc.fetch(uid, m, start, end)
        if got is None:
            return FamilyMemberDay(name=m.name, unavailable=True)
        busy_only, rows = got
        lines = busy_lines(rows, tz) if busy_only else event_lines(rows, tz)
        return FamilyMemberDay(name=m.name, events=lines, busy_only=busy_only)

    async def section(self, uid: str, tz: ZoneInfo, day: date) -> FamilySection | None:
        members = await self._svc.members(uid)
        if not members:
            return None
        start = datetime.combine(day, time(0), tzinfo=tz)
        end = start + timedelta(days=1)
        rows = await asyncio.gather(*(self._one(uid, m, start, end, tz) for m in members))
        return FamilySection(members=tuple(rows), state="ok")


__all__ = ["FamilyBrief", "busy_lines", "event_lines"]
