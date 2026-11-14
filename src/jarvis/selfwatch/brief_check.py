# src/jarvis/selfwatch/brief_check.py
"""The morning brief not made (docs/plans/r14-hardening.md D5): today's brief is absent or failed
`selfwatch_brief_grace_min` (60) minutes after his brief time. Checked by the 5-minute job, so it
works whatever time he chose; told once a day (the caller's claim, cause = the day).

The brief service is read rarely: `BriefService.today(uid)` once a day to learn the brief's time
(and whether it is on), then again only at that time plus the grace, until the day is settled
(ready, missed and told, or off). Only the status and the time are read, never the brief.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

MISSED = frozenset({"none", "failed"})  # a stale "generating" claim already reads as failed


class TodayLike(Protocol):
    date: str
    tz: str
    status: str
    due_at: datetime | None


class BriefLike(Protocol):
    async def today(self, uid: str) -> TodayLike: ...


@dataclass(frozen=True)
class _Day:
    day: str
    due: datetime | None
    settled: bool
    tz: ZoneInfo


def _zone(name: str, default: ZoneInfo) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ValueError, KeyError, OSError):
        return default


class BriefCheck:
    def __init__(
        self, brief: Callable[[], BriefLike | None], *, grace: timedelta, tz: ZoneInfo
    ) -> None:
        self._brief = brief
        self._grace = grace
        self._tz = tz
        self._days: dict[str, _Day] = {}

    def _waiting(self, uid: str, now: datetime) -> bool:
        """Nothing to read now: today is settled, or its time plus the grace hasn't come."""
        known = self._days.get(uid)
        if known is None or now.astimezone(known.tz).date().isoformat() != known.day:
            return False
        if known.settled:
            return True
        return known.due is not None and now < known.due + self._grace

    async def missed(self, uid: str, now: datetime) -> tuple[str, str] | None:
        """(the day, the local time it was due by) when today's brief was missed; else None.
        Raises when the brief can't be read (the job counts it)."""
        svc = self._brief()
        if svc is None or self._waiting(uid, now):
            return None
        view = await svc.today(uid)
        tz = _zone(view.tz, self._tz)
        due = view.due_at
        late = due is not None and now >= due + self._grace
        missed = late and view.status in MISSED
        settled = due is None or view.status == "ready" or missed
        self._days[uid] = _Day(view.date, due, settled, tz)
        if not missed or due is None:
            return None
        return view.date, f"{(due + self._grace).astimezone(tz):%H:%M}"


__all__ = ["MISSED", "BriefCheck", "BriefLike", "TodayLike"]
