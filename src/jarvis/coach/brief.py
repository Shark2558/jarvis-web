# src/jarvis/coach/brief.py
"""R8 rows 182 and 183 (docs/plans/r8-vision.md 4.7, D12; builder C): the day strip's one line in
the brief's Helpers section, about yesterday:

    "Yesterday at your desk: 5 h 45 min; longest sitting stretch 2 h 05 min;
     screen time 6 h 10 min."  (one line)

A `BriefContributor` (`jarvis.helpers.ports`): a fixed template with his own numbers, never AI
input. That section is also e-mailed and sent to Telegram, so the line carries only the desk time,
the longest stretch and the screen time in total: never posture (health data, ADR-51), never a
program's name, never a time of day. Nothing when nothing was seen (the coach off, no kit) or the
day can't be read.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta, tzinfo

from jarvis.coach.day import DayService, hm
from jarvis.logging import get_logger

log = get_logger(__name__)

NAME = "coach"
MIN_DESK_S = 600  # under ten minutes seen: no line


class CoachDayBrief:
    name = NAME

    def __init__(self, days: DayService) -> None:
        self._days = days

    async def lines(self, uid: str, tz: tzinfo, day: date) -> Sequence[str]:
        del tz  # the day service keeps his zone
        try:
            got = await self._days.day(uid, day - timedelta(days=1))
        except Exception as exc:  # noqa: BLE001 - the brief never fails for one line
            log.warning("brief: no day-strip line", extra={"error": type(exc).__name__})
            return ()
        totals = got.totals or {}
        desk = sum(totals.get(k, 0) for k in ("desk", "phone", "eating"))
        if desk < MIN_DESK_S:
            return ()
        bits = [f"Yesterday at your desk: {hm(desk)}"]
        if got.longest is not None:
            bits.append(f"longest sitting stretch {hm(got.longest.end - got.longest.start)}")
        if got.screen is not None and got.screen.state == "ok" and got.screen.active_minutes:
            bits.append(f"screen time {hm(round(got.screen.active_minutes * 60))}")
        return ("; ".join(bits) + ".",)


__all__ = ["MIN_DESK_S", "NAME", "CoachDayBrief"]
