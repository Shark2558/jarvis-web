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
)


@dataclass(frozen=True)
class AlertResult:
    sent: bool
    reason: str = ""


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
