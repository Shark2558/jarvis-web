# src/jarvis/health/tools.py
"""`systems_check` (R4 D6, row `systems`, R1): "Jarvis, run a systems check". Read-only; runs the
probes and answers with the spoken briefing (R5.1 D5: every system checked, what is broken and
what that breaks, vitals, one closing question) plus one row per integration and the concerns.
Every word in the result is JARVIS's own (fixed labels, reasons and briefing templates), so it is
vouched as trusted. No model call: the no-AI router reads `spoken` aloud as it is."""

from __future__ import annotations

from typing import Any

from jarvis.core.guardrails import ActionRisk
from jarvis.health.report import view
from jarvis.health.service import HealthService
from jarvis.tools.base import Tool
from jarvis.tools.context import require_tool_context
from jarvis.tools.provenance import vouch

RAN = "Ran a systems check"


class HealthAPI:
    def __init__(self, svc: HealthService) -> None:
        self._svc = svc

    async def check(self, _a: dict[str, Any]) -> Any:
        uid = require_tool_context().user_id
        report = await self._svc.check(uid)
        brief = await self._svc.briefing(uid, report)
        out = view(report)
        out["headline"] = out["spoken"]  # the R4 one-liner
        out["spoken"] = brief.spoken  # R5.1 D5: the tool and the voice say the full briefing
        out["concerns"] = [c.to_json() for c in brief.concerns]
        return vouch(out, True)


def health_tools(svc: HealthService) -> list[Tool]:
    api = HealthAPI(svc)
    return [
        Tool(
            "systems_check",
            "Run a systems check: ping every JARVIS connection (AI brain, Google, Telegram, "
            "home bridge, document store, Redis, web search) and read Vitals (AI spend, "
            "allowances, expiring keys). Read the 'spoken' briefing aloud exactly as given; it "
            "ends by offering a reminder for anything in 'concerns'. Works with the AI switched "
            "off.",
            {"type": "object", "properties": {}},
            ActionRisk.READ_ONLY,
            api.check,
            agent="health",
            may_vouch=True,
            activity_words=RAN,
        )
    ]


__all__ = ["RAN", "HealthAPI", "health_tools", "view"]
