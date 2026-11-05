# src/jarvis/camera/guard.py
"""Disarming, wherever it happens, needs the bound proof and is audited first (R3 D8; integrated
review S4).

- `audited_disarm`: the one way a `DisarmPass` becomes a disarm. The audit line is written FIRST
  (a security downgrade is never unrecorded); if the audit is down, nothing is switched off.
- `ArmedUnlinkGuard`: unlinking the laptop (Integrations -> Home -> Unlink, or deleting the home
  link in Privacy) wipes the arm state, which switches the alarm off. So while armed it needs
  exactly what the Disarm button needs (`DisarmGate.panel_pass`: never a bearer token; a passkey
  check bound to this home and arm rev, or a Google sign-in under 5 minutes old), and the disarm
  is audited and done before anything is unlinked. Unlinking a disarmed home stays simple.
"""

from __future__ import annotations

from typing import Any

from jarvis.camera.alarm import Alarm, DisarmGate, DisarmPass
from jarvis.camera.models import SetVia
from jarvis.camera.ports import AlarmRefused, CameraUnavailable
from jarvis.core.guardrails import ActionRisk
from jarvis.logging import get_logger
from jarvis.permissions.errors import PasskeyRejected, PasskeyRequired
from jarvis.tools.audit import AuditTrail

log = get_logger(__name__)

AUDIT_DOWN = "The alarm can't be switched off while the audit is down."
DISARM_FIRST = "The alarm is on. Disarm it in the Home panel first, then delete the home link."
ARMED = "The alarm is on. Disarm it in the Home panel first."


async def audited_disarm(
    alarm: Alarm,
    approved: DisarmPass,
    audit: AuditTrail | None,
    *,
    where: str,
    via: SetVia = "console",
) -> None:
    """Audit the disarm, then disarm. Refuses (`CameraUnavailable`) when there is no audit."""
    if audit is None:
        raise CameraUnavailable(AUDIT_DOWN)
    try:
        await audit.append(
            agent="home",
            tool="home_disarm",
            risk=ActionRisk.IRREVERSIBLE,
            outcome="executed",
            args={},
            detail=f"{where}, {approved.how}",
        )
    except Exception as exc:  # noqa: BLE001 - fail closed: never an unrecorded downgrade
        log.error("AUDIT WRITE FAILED for a disarm", extra={"error": type(exc).__name__})
        raise CameraUnavailable(AUDIT_DOWN) from None
    await alarm.disarm(approved.uid, approved, via=via)


class ArmedUnlinkGuard:
    def __init__(self, gate: DisarmGate, alarm: Alarm, audit: AuditTrail | None) -> None:
        self._gate = gate
        self._alarm = alarm
        self._audit = audit

    async def armed(self, uid: str) -> bool:
        """The cloud's arm state; unreadable counts as armed (never unlink blind)."""
        try:
            return (await self._alarm.record(uid)).armed
        except CameraUnavailable:
            return True

    async def check(
        self, uid: str, proof: Any, *, fresh_left_s: int | None, where: str, from_panel: bool
    ) -> None:
        """Disarm (audited) with the Disarm button's proof when armed; nothing when disarmed.
        Raises what the gate raises. `from_panel=False` (Privacy, which can't ask for the
        Disarm passkey): a missing passkey says "disarm first" in plain words."""
        try:
            approved = await self._gate.panel_pass(uid, proof, fresh_left_s=fresh_left_s)
        except (PasskeyRequired, PasskeyRejected):
            if from_panel:
                raise
            raise AlarmRefused("disarm_first", DISARM_FIRST) from None
        if approved is not None:
            await audited_disarm(self._alarm, approved, self._audit, where=where)


__all__ = ["ARMED", "DISARM_FIRST", "ArmedUnlinkGuard", "audited_disarm"]
