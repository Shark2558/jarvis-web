# src/jarvis/watch/brief.py
"""The brief's sleep line (docs/plans/r7-mobile.md D18; I0 seam 23; owner question 19).

`SleepBrief` is Part D's `services["brief"]`. The wiring reads every part's `brief` service as a
Helpers-section contributor (`lines(uid, tz, day)`), and that section is also in the e-mailed
inbox copy (`brief.render.render_text`) and on Telegram: so `lines` is ALWAYS empty and sleep never
rides it. The sleep line has its own pinned slot instead, `BriefData.sleep` (`SleepLine
{minutes, start, end, source}`), which `render_text` does not read: `sleep(uid, tz, day)` fills
it, for the console's brief only ("Sleep: 6 h 40 min, 23:50 to 06:30 · from your watch",
`sleep.brief_text`). Wiring `sleep()` into `BriefService` and drawing the line in the console's
brief is I1's (INTEGRATION-D.md, "Needs I1").
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, tzinfo

from jarvis.brief.models import SleepLine
from jarvis.logging import get_logger
from jarvis.watch.service import WatchService
from jarvis.watch.sleep import sleep_line

log = get_logger(__name__)


class SleepBrief:
    name = "watch"

    def __init__(self, watch: WatchService) -> None:
        self._watch = watch

    async def lines(self, uid: str, tz: tzinfo, day: date) -> Sequence[str]:
        """Never a line in the Helpers section (it is e-mailed and sent to Telegram)."""
        del uid, tz, day
        return ()

    async def sleep(self, uid: str, tz: tzinfo, day: date) -> SleepLine | None:
        """Last night for the console's brief, or None (no night, off, or unreadable)."""
        del tz  # each session keeps the clock of where he slept
        if not self._watch.enabled or not self._watch.sealed:
            return None
        try:
            night = await self._watch.night(uid, day)
        except Exception as exc:  # noqa: BLE001 - the brief never fails for one line
            log.warning("brief: no sleep line", extra={"error": type(exc).__name__})
            return None
        return None if night is None else sleep_line(night)


__all__ = ["SleepBrief"]
