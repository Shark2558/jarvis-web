# src/jarvis/alerts.py
"""The alerts port (R1 D6; Layer 8 notifications). Other features call it; Telegram implements it.

`AlertSink.send(uid, text, kind=...)` never raises for "can't send": it returns an `AlertResult`
with `sent=False` and a short reason. `text` is always written by JARVIS code from a fixed
template, never model text and never other people's words. `NoAlerts` is used when Telegram is off
or unpaired.

R3 (docs/plans/r3-home-camera.md D10, D12): the home kinds, and two keywords every sink accepts:
`silent` (deliver without a sound) and `photo` (one small JPEG for a burglar alert the owner opted
in to; held in memory, never stored, logged or audited). A sink that can't do either ignores it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

AlertKind = Literal[
    "approval_waiting",
    "offline_on",
    "offline_off",
    "brief_ready",
    "vault_expiry",
    "test",
    # R3 D10: home alerts (the level of each is notify.ports.DEFAULT_URGENCY)
    "home_intruder",
    "home_hazard",
    "home_package",
    "home_greeting",
    "home_offline",
    "home_online",
    "home_arm_failed",
    "home_summary",
    # R5.1 (docs/plans/r5-1-observations.md D3): the laptop stopped answering while DISARMED
    "home_offline_idle",
    # R4 (docs/plans/r4-vitals-health-people.md D4, D6): vitals + self-health. Levels in
    # notify.ports.DEFAULT_URGENCY: vitals_critical/health_fault important (D13), the rest info.
    "vitals_warn",
    "vitals_critical",
    "health_fault",
    "health_recovered",
    "health_degraded",
    # R6 (docs/plans/r6-build-book.md D7, D14): the build book. All "important" daytime rings
    # (notify.policy DAYTIME_RING_KINDS): held in quiet hours, rung in waking hours.
    "book_sealed",
    "book_seal_failed",
    "book_session_closed",
]
HOME_ALERT_KINDS: tuple[AlertKind, ...] = (
    "home_intruder",
    "home_hazard",
    "home_package",
    "home_greeting",
    "home_offline",
    "home_online",
    "home_arm_failed",
    "home_summary",
    "home_offline_idle",
)


@dataclass(frozen=True)
class AlertResult:
    """`queued`: not sent yet but kept to go out later (an alert held for quiet hours goes out in
    the morning summary), so a caller must not send it again."""

    sent: bool
    reason: str = ""
    queued: bool = False


@runtime_checkable
class AlertSink(Protocol):
    async def send(
        self,
        uid: str,
        text: str,
        *,
        kind: AlertKind,
        silent: bool = False,
        photo: bytes | None = None,
    ) -> AlertResult: ...


class NoAlerts:
    """The sink when nothing can deliver alerts: sends nothing and says why."""

    def __init__(self, reason: str = "not set up") -> None:
        self.reason = reason

    async def send(
        self,
        uid: str,
        text: str,
        *,
        kind: AlertKind,
        silent: bool = False,
        photo: bytes | None = None,
    ) -> AlertResult:
        return AlertResult(sent=False, reason=self.reason)


__all__ = ["HOME_ALERT_KINDS", "AlertKind", "AlertResult", "AlertSink", "NoAlerts"]
