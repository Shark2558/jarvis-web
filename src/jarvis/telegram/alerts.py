# src/jarvis/telegram/alerts.py
"""Alerts over Telegram (R1 D6): the `AlertSink` other features call. Fixed-template text written
by JARVIS code (never model text, never other people's words), at most 300 characters, plain; at
most 10 an hour and 50 a day per owner (an unreadable counter fails closed); each one audited
(agent "alerts", tool `telegram_alert`, R1)."""

from __future__ import annotations

import re

from jarvis.alerts import AlertKind, AlertResult
from jarvis.core.guardrails import ActionRisk
from jarvis.logging import get_logger
from jarvis.telegram.client import TelegramClient, TelegramError
from jarvis.telegram.store import TelegramStore
from jarvis.tools.audit import AuditTrail

log = get_logger(__name__)
MAX_ALERT_CHARS = 300
MAX_PER_HOUR = 10
MAX_PER_DAY = 50
ALERT_TEXT: dict[str, str] = {
    "approval_waiting": "JARVIS has something waiting for your approval in the console.",
    "offline_on": "Offline mode is on: your laptop is answering. Changes will ask first.",
    "offline_off": "Offline mode is off: JARVIS is back on its usual brain.",
    "brief_ready": "Your morning brief is ready in the console.",
    "test": "Test alert from JARVIS. Telegram alerts are working.",
}
_TOGGLE = {
    "approval_waiting": "approval_waiting",
    "offline_on": "offline",
    "offline_off": "offline",
    "brief_ready": "brief_ready",
}


def plain(text: str) -> str:
    """One clean line of at most MAX_ALERT_CHARS characters."""
    one = re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", text)).strip()
    return one if len(one) <= MAX_ALERT_CHARS else one[: MAX_ALERT_CHARS - 1].rstrip() + "…"


class TelegramAlerts:
    def __init__(self, client: TelegramClient, store: TelegramStore, audit: AuditTrail) -> None:
        self._client = client
        self._store = store
        self._audit = audit

    async def send(self, uid: str, text: str, *, kind: AlertKind) -> AlertResult:
        try:
            link = await self._store.get(uid)
        except Exception as exc:  # noqa: BLE001
            log.warning("alert: link unreadable", extra={"error": type(exc).__name__})
            return AlertResult(False, "Telegram settings couldn't be read")
        if link is None:
            return AlertResult(False, "Telegram isn't paired")
        field = _TOGGLE.get(kind)
        if field is None and kind != "test":  # R2: a kind with no switch yet is OFF, never sent
            return AlertResult(False, "switched off for this kind of alert")
        if field is not None and not getattr(link.alerts, field):
            return AlertResult(False, "switched off for this kind of alert")
        try:
            allowed = await self._store.count_alert(uid, per_hour=MAX_PER_HOUR, per_day=MAX_PER_DAY)
        except Exception as exc:  # noqa: BLE001 - fail closed
            log.warning("alert: counter unreadable", extra={"error": type(exc).__name__})
            return AlertResult(False, "alert limit couldn't be checked")
        if not allowed:
            return AlertResult(False, "alert limit reached for now")
        try:
            await self._client.send_message(link.chat_id, plain(text))
        except TelegramError:
            await self._record("failed", kind)
            return AlertResult(False, "Telegram couldn't be reached")
        await self._record("sent", kind)
        return AlertResult(True)

    async def _record(self, outcome: str, kind: str) -> None:
        try:
            await self._audit.append(
                agent="alerts",
                tool="telegram_alert",
                risk=ActionRisk.READ_ONLY,
                outcome=outcome,
                args={"kind": kind},
            )
        except Exception as exc:  # noqa: BLE001 - the alert already happened
            log.error("AUDIT WRITE FAILED for an alert", extra={"error": type(exc).__name__})


__all__ = [
    "ALERT_TEXT",
    "MAX_ALERT_CHARS",
    "MAX_PER_DAY",
    "MAX_PER_HOUR",
    "TelegramAlerts",
    "plain",
]
