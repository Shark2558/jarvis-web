# src/jarvis/notify/telegram_out.py
"""Telegram delivery for the policy (R3 D10, D12): an `AlertSink` that knows the R3 kinds.

R1's `TelegramAlerts` fails closed on a kind with no switch and has no `silent` or `photo`; it is
an I1 file, so this adapter does the same job for the policy without touching it:

- R1/R2 kinds keep R1's per-kind Telegram switches (`AlertToggles`); R3 home kinds have the policy's
  switch only (`notify/{uid}.kinds`, applied before we get here); `test` always goes.
- Normal kinds use R1's counter (10 an hour, 50 a day, unreadable -> not sent). Urgent kinds have
  their own bucket (30 an hour, 100 a day) that normal kinds can't use up; an unreadable counter
  fails OPEN for them with an in-process cap of 30 an hour (one instance only: deploy/cloudrun.sh
  pins `--max-instances 1`; raise that and this cap multiplies). Burglar rings are limited by the
  storm control to 20 an hour and 80 a day so that, with the summaries, they fit this bucket.
- SAFETY: a hazard (`home_hazard`: smoke, gas, water) is never refused by any cap here.
- `silent` -> `disable_notification`. `photo` (D12, burglar alerts only) goes through the
  `photo_sender` I1 supplies (a `sendPhoto` with `protect_content`); without one it is dropped. The
  bytes are held in memory only: never stored, logged or audited.
- Every attempt is audited as R1 does (agent "alerts", tool `telegram_alert`, kind only).
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from jarvis.alerts import AlertKind, AlertResult
from jarvis.core.guardrails import ActionRisk
from jarvis.logging import get_logger
from jarvis.notify.ports import DEFAULT_URGENCY
from jarvis.notify.store import NotifyStore
from jarvis.notify.storm import SOFT_URGENT_KINDS
from jarvis.telegram.alerts import MAX_PER_DAY, MAX_PER_HOUR, plain
from jarvis.telegram.client import TelegramClient, TelegramError
from jarvis.telegram.models import AlertToggles
from jarvis.telegram.store import TelegramStore
from jarvis.tools.audit import AuditTrail

log = get_logger(__name__)
URGENT_PER_HOUR = 30
URGENT_PER_DAY = 100
LIMIT_REASON = "alert limit reached for now"
NO_CAP_KINDS = frozenset({"home_hazard"})
SWITCHED_OFF = "switched off for this kind of alert"
# kinds that still have an R1 Telegram switch (field name on AlertToggles)
R1_TOGGLE = {
    "approval_waiting": "approval_waiting",
    "offline_on": "offline",
    "offline_off": "offline",
    "brief_ready": "brief_ready",
    "vault_expiry": "vault_expiry",
}
PhotoSender = Callable[[int, bytes, str], Awaitable[None]]


@dataclass(frozen=True)
class SentResult(AlertResult):
    photo: bool = False


class TelegramHomeAlerts:
    def __init__(
        self,
        client: TelegramClient,
        store: TelegramStore,
        notify_store: NotifyStore,
        audit: AuditTrail,
        *,
        photo_sender: PhotoSender | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._store = store
        self._notify = notify_store
        self._audit = audit
        self._photo_sender = photo_sender
        self._now = now
        self._clock = clock
        self._urgent_recent: deque[float] = deque()

    async def kind_off(self, uid: str, kind: str) -> bool:
        """Whether the owner's R1 Telegram switch for this kind is off. Not paired or unreadable
        settings use R1's defaults (vault_expiry and brief_ready off), the private direction."""
        field = R1_TOGGLE.get(kind)
        if field is None:
            return False
        try:
            link = await self._store.get(uid)
        except Exception as exc:  # noqa: BLE001
            log.warning("alert: link unreadable", extra={"error": type(exc).__name__})
            link = None
        toggles = link.alerts if link is not None else AlertToggles()
        return not getattr(toggles, field)

    async def send(
        self,
        uid: str,
        text: str,
        *,
        kind: AlertKind,
        silent: bool = False,
        photo: bytes | None = None,
    ) -> AlertResult:
        try:
            link = await self._store.get(uid)
        except Exception as exc:  # noqa: BLE001
            log.warning("alert: link unreadable", extra={"error": type(exc).__name__})
            return AlertResult(False, "Telegram settings couldn't be read")
        if link is None:
            return AlertResult(False, "Telegram isn't paired")
        field = R1_TOGGLE.get(kind)
        if field is not None and not getattr(link.alerts, field):
            return AlertResult(False, SWITCHED_OFF)
        if not await self._allowed(uid, kind):
            return AlertResult(False, LIMIT_REASON)
        sent_photo = False
        try:
            if photo is not None and self._photo_sender is not None and kind == "home_intruder":
                sent_photo = await self._try_photo(link.chat_id, photo, text)
            if not sent_photo:
                await self._client.call(
                    "sendMessage",
                    {
                        "chat_id": link.chat_id,
                        "text": plain(text),
                        "disable_notification": bool(silent),
                    },
                )
        except TelegramError:
            await self._record("failed", kind)
            return AlertResult(False, "Telegram couldn't be reached")
        await self._record("sent", kind)
        return SentResult(True, photo=sent_photo)

    async def _try_photo(self, chat_id: int, photo: bytes, text: str) -> bool:
        assert self._photo_sender is not None  # noqa: S101 - narrowed by the caller
        try:
            await self._photo_sender(chat_id, photo, plain(text))
        except Exception as exc:  # noqa: BLE001 - fall back to the text alone
            log.warning("alert photo failed", extra={"error": type(exc).__name__})
            return False
        return True

    async def _allowed(self, uid: str, kind: str) -> bool:
        if kind in NO_CAP_KINDS:
            return True
        if DEFAULT_URGENCY.get(kind) != "urgent" or kind in SOFT_URGENT_KINDS:
            # health / vitals rings use the normal bucket: the urgent one is for burglar / hazard
            try:
                return await self._store.count_alert(
                    uid, per_hour=MAX_PER_HOUR, per_day=MAX_PER_DAY
                )
            except Exception as exc:  # noqa: BLE001 - fail closed
                log.warning("alert: counter unreadable", extra={"error": type(exc).__name__})
                return False
        try:
            return await self._notify.take_urgent(
                uid, self._now(), per_hour=URGENT_PER_HOUR, per_day=URGENT_PER_DAY
            )
        except Exception as exc:  # noqa: BLE001 - fail OPEN for urgent kinds, with a local cap
            log.warning("alert: urgent counter unreadable", extra={"error": type(exc).__name__})
            return self._local_cap()

    def _local_cap(self) -> bool:
        at = self._clock()
        while self._urgent_recent and at - self._urgent_recent[0] >= 3600:
            self._urgent_recent.popleft()
        if len(self._urgent_recent) >= URGENT_PER_HOUR:
            return False
        self._urgent_recent.append(at)
        return True

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
    "LIMIT_REASON",
    "NO_CAP_KINDS",
    "R1_TOGGLE",
    "URGENT_PER_DAY",
    "URGENT_PER_HOUR",
    "PhotoSender",
    "SentResult",
    "TelegramHomeAlerts",
]
