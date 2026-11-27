# src/jarvis/coach/tools.py
"""R8 I0 seam S10 (docs/plans/r8-vision.md 4.4, ADR-51): the brain's one coach tool.

`coach_results` (R1, read-only; filed under Health & Wellbeing, group `coach`, in
`skills/catalogue.json`; private on Telegram: `coach_*` in `telegram.rules.PRIVATE_PATTERNS`)
returns kept tallies only when he asks: the coach, when, whose (his own, a person he enrolled by
name, or "Guest N") and its numbers. Never a frame, a point or a box (none is kept); never an
interpretation: the numbers as kept, and a blood-pressure reading only with the published
category and its source (`jarvis.coach.bp`). `who` "" means everyone's.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from jarvis.coach.people import CoachOff, is_who
from jarvis.coach.store import BP_USE, KEEP_DAYS, CoachStore
from jarvis.coach.usecases import BY_ID
from jarvis.core.guardrails import ActionRisk
from jarvis.tools.base import Tool
from jarvis.tools.context import require_tool_context

NAME = "coach_results"
AGENT = "coach"
DEFAULT_DAYS = 7
ACTIVITY = "Read the coach results kept for you"
USES: tuple[str, ...] = (*BY_ID, BP_USE)
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "days": {"type": "integer", "minimum": 1, "maximum": KEEP_DAYS},
        "use": {"type": "string", "enum": list(USES)},
        "who": {"type": "string", "description": "me, a person's fp_ id, a guest's gst_ id"},
    },
    "additionalProperties": False,
}
Names = Callable[[str], Awaitable[Mapping[str, str]]]  # {who: the name he knows them by}


def _check(args: dict[str, Any]) -> None:
    days = args.get("days", DEFAULT_DAYS)
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= KEEP_DAYS:
        raise ValueError(f"days must be a whole number from 1 to {KEEP_DAYS}")
    if args.get("use") not in (None, *USES):
        raise ValueError("use must be one of: " + ", ".join(USES))
    if args.get("who") not in (None, "") and not is_who(args.get("who")):
        raise ValueError("who must be me, an enrolled person's id or a guest's id")


def message(count: int, days: int, honorific: str) -> str:
    span = "today" if days == 1 else f"in the last {days} days"
    if count == 0:
        return f"No coach results were kept {span}, {honorific}."
    noun = "result" if count == 1 else "results"
    return f"{count} coach {noun} kept {span}, {honorific}."


def results_tool(store: CoachStore, names: Names, *, honorific: str = "Sir") -> Tool:
    async def run(args: dict[str, Any]) -> dict[str, Any]:
        _check(args)
        days, use, who = args.get("days", DEFAULT_DAYS), args.get("use"), args.get("who") or None
        uid = require_tool_context().user_id
        try:
            items = await store.list(uid, days=days, who=who)
        except CoachOff as exc:
            return {"count": 0, "results": [], "message": str(exc)}
        known = await names(uid)
        picked = [
            {
                "use": i.get("use"),
                "at": i.get("kept_at"),
                "who": known.get(str(i.get("who")), "Guest"),
                "tally": i.get("tally"),
            }  # fmt: skip
            for i in items
            if use in (None, i.get("use"))
        ]
        return {
            "count": len(picked),
            "results": picked,
            "message": message(len(picked), days, honorific),
        }

    return Tool(
        name=NAME,
        description=(
            "Read the coach results kept from the camera coaches (posture, the day strip, the "
            "desk and workout coaches, blood-pressure readings he confirmed): counts, times and "
            "scores only, never a picture. Say the numbers as they are; never diagnose, never "
            "suggest a medicine or a dose."
        ),
        input_schema=SCHEMA,
        risk=ActionRisk.READ_ONLY,
        run=run,
        agent=AGENT,
        summary_template="Read the kept coach results",
        check=_check,
        activity_words=ACTIVITY,
    )


__all__ = ["ACTIVITY", "NAME", "SCHEMA", "USES", "message", "results_tool"]
