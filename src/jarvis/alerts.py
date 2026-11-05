# src/jarvis/alerts.py
"""The alerts port (R1 D6; Layer 8 notifications). Other features call it; Telegram implements it.

`AlertSink.send(uid, text, kind=...)` never raises for "can't send": it returns an `AlertResult`
with `sent=False` and a short reason. `text` is always written by JARVIS code from a fixed
template, never model text and never other people's words. `NoAlerts` is used when Telegram is off
or unpaired.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

AlertKind = Literal[
    "approval_waiting", "offline_on", "offline_off", "brief_ready", "vault_expiry", "test"
]


@dataclass(frozen=True)
class AlertResult:
    sent: bool
    reason: str = ""


@runtime_checkable
class AlertSink(Protocol):
    async def send(self, uid: str, text: str, *, kind: AlertKind) -> AlertResult: ...


class NoAlerts:
    """The sink when nothing can deliver alerts: sends nothing and says why."""

    def __init__(self, reason: str = "not set up") -> None:
        self.reason = reason

    async def send(self, uid: str, text: str, *, kind: AlertKind) -> AlertResult:
        return AlertResult(sent=False, reason=self.reason)


__all__ = ["AlertKind", "AlertResult", "AlertSink", "NoAlerts"]
