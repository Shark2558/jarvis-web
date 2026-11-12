# src/jarvis/series/batch_tools.py
"""The two batch tools as the gateway sees them (R11.1 O2; docs/plans/r11-1-observations.md D4,
D5, D21-A): `calendar_create_events` and `calendar_undo_events`, both R2 with `ask_when` always
(ONE approval card, whoever asks). What they do is `jarvis.series.batch.BatchAPI`."""

from __future__ import annotations

from jarvis.core.guardrails import ActionRisk
from jarvis.series.batch import BatchAPI
from jarvis.tools.base import Tool
from jarvis.tools.calendar_batch import CREATE, NAME_MAX, PREFIX_MAX, UNDO

_ISO = {"type": "string", "description": "ISO 8601 date-time, e.g. 2027-01-15T19:00:00+05:30"}
_EVENT = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "start": _ISO,
        "end": _ISO,
        "description": {"type": "string"},
        "location": {"type": "string"},
        "reminders_minutes": {"type": "array", "items": {"type": "integer"}, "maxItems": 5},
        "n": {"type": "integer", "description": "Its number in the batch; only when retrying."},
    },
    "required": ["summary", "start", "end"],
}


def batch_tools(api: BatchAPI, *, limit: int) -> list[Tool]:
    return [
        Tool(
            CREATE,
            "Add several events to the owner's calendar on ONE approval card that lists them "
            f"all (1 to {limit} events, no guests). More than three events -> this tool, never "
            "many calendar_create_event calls. title_prefix puts '<prefix> - ' before every "
            "title. series {name} makes it a plan JARVIS follows up (it asks after each session "
            "whether it happened). To retry events that failed, send only those with the batch "
            "id from the result. Nothing is added until the owner approves.",
            {
                "type": "object",
                "properties": {
                    "events": {"type": "array", "items": _EVENT, "minItems": 1, "maxItems": limit},
                    "title_prefix": {"type": "string", "maxLength": PREFIX_MAX},
                    "series": {
                        "type": "object",
                        "properties": {"name": {"type": "string", "maxLength": NAME_MAX}},
                        "required": ["name"],
                    },
                    "batch": {"type": "string", "description": "Only when retrying a batch."},
                },
                "required": ["events"],
            },
            ActionRisk.REVERSIBLE,
            api.create,
            agent="google",
            check=api.check,
            summarize=api.summarize,
            preview=api.preview_create,
            ask_when=lambda _a: True,
            may_vouch=True,
            activity_words="Calendar events added in one batch",
        ),
        Tool(
            UNDO,
            "Remove every event of one calendar_create_events batch that the owner has not "
            "changed since (each is kept in Recently deleted for 30 days). The owner approves "
            "it first; an event he changed is left alone.",
            {"type": "object", "properties": {"batch": {"type": "string"}}, "required": ["batch"]},
            ActionRisk.REVERSIBLE,
            api.undo,
            agent="google",
            check=api.check_undo,
            preview=api.preview_undo,
            ask_when=lambda _a: True,
            activity_words="A batch of calendar events removed",
        ),
    ]


__all__ = ["batch_tools"]
