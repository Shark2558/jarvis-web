# src/jarvis/watch/tools.py
"""The watch and sleep tools (docs/plans/r7-mobile.md D18, D25; Layer 5 Learning & wellbeing).
Every call goes through the gateway under the "Watch and sleep" row; on Telegram they are private
reads (`watch_*`, `sleep_*` in `telegram.rules.PRIVATE_PATTERNS`); a brain that learns never gets
tools at all (`core.brain._tools_on`).

| tool | risk | says |
|---|---|---|
| `sleep_last_night` | R1 | last night's minutes, times, source and stages (when written) |
| `sleep_week` | R1 | the last 7 nights' average and the spread of bedtimes |
| `watch_today` | R1 | today's steps and heart rate (lowest, average, highest), last synced |
| `sleep_note` | R2 | keeps a night he typed ("23:30" to "06:00"), marked "typed by you" |

Each result is `{"message": <a fixed sentence>}` (`jarvis.watch.words`), the same words in No-AI
mode, by voice and in chat. A refusal or an off switch is `{"message", "refused" | "unavailable"}`
in plain words. The results are his own numbers and JARVIS's words (`trusted_output`); Activity
shows fixed words only (`activity_words`), never a time or a value.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from jarvis.core.guardrails import ActionRisk
from jarvis.logging import get_logger
from jarvis.tools.base import Tool
from jarvis.tools.context import require_tool_context
from jarvis.watch.models import source_of
from jarvis.watch.service import NoteRefused, WatchService
from jarvis.watch.sleep import FROM
from jarvis.watch.store import WatchOff, WatchUnavailable
from jarvis.watch.words import (
    ESTIMATE,
    NOTHING_TODAY,
    SWITCHED_OFF,
    last_night_words,
    noted_words,
    synced_words,
    week_words,
)

log = get_logger(__name__)
AGENT = "watch"
R1, R2 = ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE
_NONE: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}
_HHMM = {"type": "string", "description": "24-hour time HH:MM, e.g. 23:30", "maxLength": 5}
Run = Callable[[str], Awaitable[str]]


def _uid() -> str:
    return require_tool_context().user_id


def _guarded(svc: WatchService, read: Run) -> Callable[[dict[str, Any]], Awaitable[Any]]:
    async def run(_: dict[str, Any]) -> dict[str, Any]:
        if not svc.enabled:
            return {"message": SWITCHED_OFF, "unavailable": True}
        try:
            return {"message": await read(_uid())}
        except (WatchOff, WatchUnavailable) as exc:
            return {"message": str(exc), "unavailable": True}

    return run


def watch_tools(svc: WatchService) -> tuple[Tool, ...]:
    async def last_night(uid: str) -> str:
        return last_night_words(await svc.night(uid, svc.today()))

    async def this_week(uid: str) -> str:
        return week_words(await svc.week(uid, svc.today()))

    async def today(uid: str) -> str:
        day = await svc.day(uid, svc.today())
        state = await svc.state(uid)
        local = state.last_sync.astimezone(svc.zone()) if state.last_sync else None
        parts: list[str] = []
        if day is not None and day.steps is not None:
            src = source_of(day.steps.writer)
            parts.append(f"Today so far: {day.steps.count:,} steps, {FROM[src]}.")
        if day is not None and day.heart is not None:
            h, src = day.heart, source_of(day.heart.writer)
            parts.append(
                f"Heart rate today: {h.min} lowest, {h.avg} average, {h.max} highest, "
                f"{FROM[src]}. {ESTIMATE[src]}"
            )
        if not parts:
            parts.append(NOTHING_TODAY)
        parts.append(synced_words(state, local))
        return " ".join(parts)

    async def note(args: dict[str, Any]) -> dict[str, Any]:
        if not svc.enabled:
            return {"message": SWITCHED_OFF, "unavailable": True}
        try:
            night = await svc.note(_uid(), str(args.get("start", "")), str(args.get("end", "")))
        except NoteRefused as exc:
            return {"message": str(exc), "refused": True}
        except (WatchOff, WatchUnavailable) as exc:
            return {"message": str(exc), "unavailable": True}
        return {"message": noted_words(night)}

    return (
        Tool(
            "sleep_last_night",
            "How he slept last night: minutes, times, whether the watch or the phone measured it, "
            "and stages when the watch wrote them. Estimates, never a diagnosis.",
            _NONE,
            R1,
            _guarded(svc, last_night),
            agent=AGENT,
            trusted_output=True,
            activity_words="Read last night's sleep",
        ),
        Tool(
            "sleep_week",
            "His last 7 nights: average sleep and the spread of bedtimes. Estimates only.",
            _NONE,
            R1,
            _guarded(svc, this_week),
            agent=AGENT,
            trusted_output=True,
            activity_words="Read this week's sleep",
        ),
        Tool(
            "watch_today",
            "Today's steps and heart rate (lowest, average, highest) from his watch or phone, and "
            "when the phone last synced.",
            _NONE,
            R1,
            _guarded(svc, today),
            agent=AGENT,
            trusted_output=True,
            activity_words="Read today's steps and heart rate",
        ),
        Tool(
            "sleep_note",
            "Keep the time he says he slept last night (his own words, 24-hour HH:MM), marked "
            "'typed by you'. Only when he says it himself.",
            {
                "type": "object",
                "properties": {"start": _HHMM, "end": _HHMM},
                "required": ["start", "end"],
                "additionalProperties": False,
            },
            R2,
            note,
            agent=AGENT,
            summary_template="Note that you slept {start} to {end}",
            trusted_output=True,
            activity_words="Noted a sleep time you typed",
        ),
    )


__all__ = ["AGENT", "watch_tools"]
