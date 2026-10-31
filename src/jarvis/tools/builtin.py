# src/jarvis/tools/builtin.py
"""In-memory tools that prove the spine end to end. Real connectors replace them in later
slices; the Tool contract stays the same."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from jarvis.core.guardrails import ActionRisk
from jarvis.tools.base import Tool


@dataclass
class InMemoryWorld:
    calendar: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {
            "today": [
                {"time": "09:30", "title": "Daily stand-up"},
                {"time": "11:00", "title": "Steering committee review"},
            ],
            "tomorrow": [{"time": "10:00", "title": "Vendor demo"}],
        }
    )
    tasks: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {"title": "Finalise Q4 risk register", "priority": "high"},
        ]
    )
    reminders: list[dict[str, Any]] = field(default_factory=list)
    sent: list[dict[str, Any]] = field(default_factory=list)


def builtin_tools(world: InMemoryWorld) -> list[Tool]:
    def get_calendar(a: dict[str, Any]) -> dict[str, Any]:
        day = a.get("day", "today")
        return {"day": day, "events": world.calendar.get(day, [])}

    def list_tasks(_: dict[str, Any]) -> dict[str, Any]:
        return {"tasks": world.tasks}

    def create_reminder(a: dict[str, Any]) -> dict[str, Any]:
        r = {"text": str(a["text"]), "when": str(a["when"])}
        world.reminders.append(r)
        return {"created": True, "reminder": r}

    def send_message(a: dict[str, Any]) -> dict[str, Any]:
        m = {"to": str(a["to"]), "body": str(a["body"])}
        world.sent.append(m)
        return {"sent": True, "to": m["to"]}

    return [
        Tool(
            "get_calendar",
            "List the owner's calendar events for 'today' or 'tomorrow'.",
            {
                "type": "object",
                "properties": {"day": {"type": "string", "enum": ["today", "tomorrow"]}},
            },
            ActionRisk.READ_ONLY,
            get_calendar,
            agent="task_productivity",
        ),
        Tool(
            "list_tasks",
            "List the owner's open tasks.",
            {"type": "object", "properties": {}},
            ActionRisk.READ_ONLY,
            list_tasks,
            agent="task_productivity",
        ),
        Tool(
            "create_reminder",
            "Create a reminder (reversible).",
            {
                "type": "object",
                "properties": {"text": {"type": "string"}, "when": {"type": "string"}},
                "required": ["text", "when"],
            },
            ActionRisk.REVERSIBLE,
            create_reminder,
            agent="task_productivity",
            summary_template="Remind at {when}: {text}",
        ),
        Tool(
            "send_message",
            "Send a message to a contact. Irreversible: requires owner approval.",
            {
                "type": "object",
                "properties": {"to": {"type": "string"}, "body": {"type": "string"}},
                "required": ["to", "body"],
            },
            ActionRisk.IRREVERSIBLE,
            send_message,
            agent="communication",
            summary_template="Send a message to {to}",
        ),
    ]
