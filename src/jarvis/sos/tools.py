# src/jarvis/sos/tools.py
"""The brain's ONLY SOS tool (docs/plans/r7-mobile.md D19, D25): `sos_status`, an R1 read under the
"Emergency SOS" row. It says how many contacts there are, how many joined, when the last SOS was
sent and how he sends one himself: counts and times, never a name or a number (it stays
answerable on Telegram). No tool sends an SOS: the send is the owner's hold and countdown, on the
web sheet or the phone, never the brain.
"""

from __future__ import annotations

from typing import Any

from jarvis.core.guardrails import ActionRisk
from jarvis.sos.service import SosService
from jarvis.tools.base import Tool
from jarvis.tools.context import require_tool_context


def sos_tools(svc: SosService) -> tuple[Tool, ...]:
    async def run(_: dict[str, Any]) -> dict[str, Any]:
        return {"message": await svc.status_words(require_tool_context().user_id)}

    return (
        Tool(
            "sos_status",
            "His emergency SOS set-up: how many contacts and how many joined, and when the last "
            "SOS was sent. It cannot send an SOS: only his hold and countdown can.",
            {"type": "object", "properties": {}, "additionalProperties": False},
            ActionRisk.READ_ONLY,
            run,
            agent="sos",
            trusted_output=True,
            activity_words="Read your SOS set-up",
        ),
    )


__all__ = ["sos_tools"]
