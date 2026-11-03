# src/jarvis/api/settings_audit.py
"""An owner's change to what JARVIS may reach, in the append-only audit chain (slice 12 security
review SEC-3; Layer 4 cross-cutting). Switching a Drive folder on or off and saving Home / Work
change what JARVIS reads and what it sends to Google, so each one is recorded like a tool call.

Only a hash of what the caller names goes in (`args`: the folder id; the FIELD NAMES of Home /
Work) — never a plain id, a folder name or an address. Recorded after the change happened: an
audit outage is logged loudly and never turned into an error for something already done (as
`api.deleted` and `permissions.service` do).
"""

from __future__ import annotations

from typing import Any

from fastapi import Request

from jarvis.core.guardrails import ActionRisk
from jarvis.logging import get_logger

log = get_logger(__name__)


async def record_change(
    request: Request, *, agent: str, tool: str, args: dict[str, Any], detail: str = ""
) -> None:
    """One "changed" entry on the app's audit chain (the gateway's). Never raises."""
    gw = getattr(request.app.state, "gateway", None)
    if gw is None:
        log.warning("no audit chain for a settings change", extra={"tool": tool})
        return
    try:
        await gw.audit.append(
            agent=agent,
            tool=tool,
            risk=ActionRisk.REVERSIBLE,
            outcome="changed",
            args=args,
            detail=detail,
        )
    except Exception as exc:  # noqa: BLE001 — it already happened
        log.error(
            "AUDIT WRITE FAILED after a settings change",
            extra={"tool": tool, "error": type(exc).__name__},
        )


__all__ = ["record_change"]
