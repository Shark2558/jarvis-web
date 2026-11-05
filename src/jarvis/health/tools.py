# src/jarvis/health/tools.py
"""`systems_check` (R4 D6, row `systems`, R1): "Jarvis, run a systems check". Read-only; runs the
probes and answers with the fixed-template line plus one row per integration. Every word in the
result is JARVIS's own (fixed labels and reasons), so it is vouched as trusted. No model call."""

from __future__ import annotations

from typing import Any

from jarvis.core.guardrails import ActionRisk
from jarvis.health.models import HealthReport
from jarvis.health.report import compose_line, spoken_label
from jarvis.health.service import HealthService
from jarvis.tools.base import Tool
from jarvis.tools.context import require_tool_context
from jarvis.tools.provenance import vouch

RAN = "Ran a systems check"


def view(report: HealthReport) -> dict[str, Any]:
    """The report as plain data (shared by the tool and the HTTP route)."""
    return {
        "overall": report.overall,
        "spoken": compose_line(report),
        "checked_at": report.at,
        "systems": [
            {
                "key": r.key,
                "name": spoken_label(r),
                "status": r.status,
                "reason": r.reason,
                "at": r.at,
            }
            for r in report.results
        ],
    }


class HealthAPI:
    def __init__(self, svc: HealthService) -> None:
        self._svc = svc

    async def check(self, _a: dict[str, Any]) -> Any:
        uid = require_tool_context().user_id
        return vouch(view(await self._svc.check(uid)), True)


def health_tools(svc: HealthService) -> list[Tool]:
    api = HealthAPI(svc)
    return [
        Tool(
            "systems_check",
            "Run a systems check: ping every JARVIS connection (AI brain, Google, Telegram, "
            "home bridge, document store, Redis, web search) and report which are fine. Read the "
            "'spoken' line aloud exactly as given. Works with the AI switched off.",
            {"type": "object", "properties": {}},
            ActionRisk.READ_ONLY,
            api.check,
            agent="health",
            may_vouch=True,
            activity_words=RAN,
        )
    ]


__all__ = ["RAN", "HealthAPI", "health_tools", "view"]
