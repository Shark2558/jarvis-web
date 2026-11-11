# src/jarvis/helpers/nudges/brief.py
"""Part C's lines for the brief's "Helpers" section (fixed templates, at most `MAX_BRIEF_LINES`):
which nudges are on today, and yesterday's water and stand-ups from his sealed log (only with the
keyring, only when something was logged). His own data on his own console; never model input.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta, tzinfo

from jarvis.helpers.nudges.models import EVERY_KINDS, LABEL
from jarvis.helpers.nudges.service import NudgeService

NAME = "nudges"


class NudgesBrief:
    name = NAME

    def __init__(self, svc: NudgeService) -> None:
        self._svc = svc

    async def lines(self, uid: str, tz: tzinfo, day: date) -> Sequence[str]:
        s = await self._svc.settings(uid)
        on = [k for k in s.on_kinds() if day.weekday() in s.nudge(k).days]
        out = []
        if on:
            bits = [
                f"{LABEL[k].lower()} every {s.nudge(k).every} min"
                if k in EVERY_KINDS
                else LABEL[k].lower()
                for k in on
            ]
            out.append("Nudges today: " + ", ".join(bits) + ".")
        if self._svc.well.on:
            got = await self._svc.well.day(uid, (day - timedelta(days=1)).isoformat())
            if got.water or got.stood:
                out.append(f"Yesterday: {got.water} glasses of water, {got.stood} stand-ups.")
        return out


__all__ = ["NAME", "NudgesBrief"]
