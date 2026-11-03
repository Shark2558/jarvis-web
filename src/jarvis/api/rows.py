# src/jarvis/api/rows.py
"""Has the owner set a permission row to Never? For the console's views and settings (slice 12 D8,
final review; Layer 1). Decided by the owner's own rules exactly as the gateway would decide a
read-only call of the row's tool, so a view never offers what every call would refuse.

- `switched_off`: which of some named tools are on a Never row. When the rules can't be read the
  view can't tell, so it offers the row (logged); a call through the gateway still fails closed.
- `switched_off_reply`: the plain 409 a settings change answers while its row is Never (Drive
  folders, Maps Home / Work): {error: "switched_off", detail}.
"""

from __future__ import annotations

from collections.abc import Mapping

from fastapi import Request
from fastapi.responses import JSONResponse

from jarvis.core.guardrails import ActionRisk
from jarvis.logging import get_logger
from jarvis.tools.policy import Effect, Policy

log = get_logger(__name__)

DRIVE_TOOL = "drive_list"  # the Drive row (drive_*)
MAPS_TOOL = "maps_route"  # the Maps row (maps_*): Home / Work are used only by routes
SWITCHED_OFF = "{what} is switched off in Permissions (Never). Change it there first."


async def switched_off(request: Request, uid: str, tools: Mapping[str, str]) -> frozenset[str]:
    """The names in `tools` ({name: tool}) whose tool the owner's rules refuse (Never)."""
    source = getattr(request.app.state, "permissions", None)
    if source is None:
        return frozenset()
    try:
        policy = Policy(await source.rules_for(uid))
    except Exception as exc:  # noqa: BLE001 — a view only; logged, never raised
        log.warning("permissions unreadable for a view", extra={"error": type(exc).__name__})
        return frozenset()
    return frozenset(
        name
        for name, tool in tools.items()
        if policy.decide(tool, ActionRisk.READ_ONLY, {}) is Effect.DENY
    )


async def is_never(request: Request, uid: str, tool: str) -> bool:
    """True when the owner set `tool`'s permission row to Never."""
    return bool(await switched_off(request, uid, {tool: tool}))


def switched_off_reply(what: str) -> JSONResponse:
    """409 {error: "switched_off", detail}: a setting of a row the owner switched off."""
    detail = SWITCHED_OFF.format(what=what)
    return JSONResponse(status_code=409, content={"error": "switched_off", "detail": detail})


__all__ = [
    "DRIVE_TOOL",
    "MAPS_TOOL",
    "SWITCHED_OFF",
    "is_never",
    "switched_off",
    "switched_off_reply",
]
