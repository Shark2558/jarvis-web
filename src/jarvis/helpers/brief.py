# src/jarvis/helpers/brief.py
"""The brief's "Helpers" section (docs/plans/r11-free-helpers.md, I0 seam 8).

`HelpersBrief(contributors)` asks every part's `BriefContributor` for its lines, each within its
own `CONTRIBUTOR_TIMEOUT_S`, at most `MAX_BRIEF_LINES` a contributor and `MAX_SECTION_LINES` in
all, each one clean line of at most `MAX_LINE` characters. The lines are the parts' own fixed
templates (bills due, birthdays, chores, the weather with its attribution, the month's spend),
never a model's words and never part of the AI summary's input. A contributor that fails or is
slow is left out (logged by class name); no lines at all means no section (None).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from datetime import date, tzinfo

from jarvis.brief.models import HelpersSection
from jarvis.helpers.ports import MAX_BRIEF_LINES, MAX_LINE, BriefContributor
from jarvis.logging import get_logger

log = get_logger(__name__)

CONTRIBUTOR_TIMEOUT_S = 3.0
MAX_SECTION_LINES = 8


def clean_line(text: object) -> str:
    """One line of plain text, at most `MAX_LINE` characters ("" when it isn't text)."""
    if not isinstance(text, str):
        return ""
    one = " ".join("".join(c if c >= " " and c != "\x7f" else " " for c in text).split())
    return one if len(one) <= MAX_LINE else one[: MAX_LINE - 1].rstrip() + "…"


class HelpersBrief:
    def __init__(
        self,
        contributors: Callable[[], Sequence[BriefContributor]],
        *,
        timeout_s: float = CONTRIBUTOR_TIMEOUT_S,
    ) -> None:
        self._contributors = contributors
        self._timeout_s = timeout_s

    async def _one(self, c: BriefContributor, uid: str, tz: tzinfo, day: date) -> list[str]:
        try:
            got = await asyncio.wait_for(c.lines(uid, tz, day), self._timeout_s)
        except Exception as exc:  # noqa: BLE001 - one helper never fails the brief
            log.warning("brief: a helper had no lines", extra={"error": type(exc).__name__})
            return []
        lines = [clean_line(x) for x in (got if isinstance(got, list | tuple) else ())]
        return [x for x in lines if x][:MAX_BRIEF_LINES]

    async def section(self, uid: str, tz: tzinfo, day: date) -> HelpersSection | None:
        everyone = list(self._contributors())
        found = await asyncio.gather(*(self._one(c, uid, tz, day) for c in everyone))
        lines = [x for chunk in found for x in chunk][:MAX_SECTION_LINES]
        return HelpersSection(lines=tuple(lines)) if lines else None


__all__ = ["CONTRIBUTOR_TIMEOUT_S", "MAX_SECTION_LINES", "HelpersBrief", "clean_line"]
