# src/jarvis/series/brief.py
"""The plans' line in the morning brief (R11.1 O2b; docs/plans/r11-1-observations.md D6): the
sessions that have no check-in yet are asked again there, once, in one line: never nagged. A
`helpers.ports.BriefContributor` (a fixed template, never AI input); I1 adds it to the brief's
Helpers section (`FixPart.services["brief"]`)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, tzinfo

from jarvis.series.service import SeriesService

NAME = "plans"


def line(n: int) -> str:
    one = n == 1
    return (
        f"{n} planned session{'' if one else 's'} {'has' if one else 'have'} no check-in: say "
        "'session done' or 'session skipped'."
    )


class PlansBrief:
    name = NAME

    def __init__(self, svc: SeriesService) -> None:
        self._svc = svc

    async def lines(self, uid: str, tz: tzinfo, day: date) -> Sequence[str]:
        del tz, day  # every open check-in counts, whenever its session was
        n = len(await self._svc.waiting(uid))
        return [line(n)] if n else []


__all__ = ["NAME", "PlansBrief", "line"]
