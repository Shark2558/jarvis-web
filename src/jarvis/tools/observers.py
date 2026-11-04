# src/jarvis/tools/observers.py
"""Gateway observers (R1 I0 seam; Layer 4 to 7): listeners told what the gateway did.

The gateway audits first, then calls `notify` with a `GatewayEvent` for each call that ended in
`executed`, `error`, `awaiting_confirmation`, `denied` or `declined`. Observers (the Activity
recorder) can never change or fail the call: `notify` swallows and logs every error. An event has
no result text of its own: `result` is the gateway's `GatewayResult` (None for a decline), and
`entry` is the audit entry just written (None when the audit was down after the tool ran).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from jarvis.core.guardrails import ActionRisk
from jarvis.logging import get_logger
from jarvis.tools.audit import AuditEntry

log = get_logger(__name__)


@dataclass(frozen=True)
class GatewayEvent:
    outcome: str  # executed | error | awaiting_confirmation | denied | declined
    tool: str
    agent: str
    risk: ActionRisk  # what the call itself can do
    args: dict[str, Any]
    scope: str | None  # "<user_id>:<session_id>"
    entry: AuditEntry | None
    result: Any = None  # the GatewayResult (None for a decline)


class GatewayObserver(Protocol):
    async def on_event(self, event: GatewayEvent) -> None: ...


async def notify(observers: Sequence[GatewayObserver], event: GatewayEvent) -> None:
    """Tell every observer; one that raises is logged (class name only) and skipped."""
    for obs in observers:
        try:
            await obs.on_event(event)
        except Exception as exc:  # noqa: BLE001 - an observer never fails a tool call
            log.warning(
                "gateway observer failed",
                extra={"observer": type(obs).__name__, "error": type(exc).__name__},
            )


__all__ = ["GatewayEvent", "GatewayObserver", "notify"]
