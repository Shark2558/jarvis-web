# src/jarvis/notify/service.py
"""`NotifyService`: the `Notifier` (R3 D10). Reads the owner's settings, asks the pure policy,
applies storm control, then delivers to Telegram and Web Push in parallel. Each channel's failure
is contained: a failing push never blocks Telegram and the other way round. No model call.

Names: `named_message` is used only when names in alerts are on and the signal is not a child;
a child is never named on any channel. The photo (D12) goes to Telegram only, for a burglar alert
that rings, and only when the snapshot opt-in is on. One audit line per alert with kinds and
counts, never text (the channels audit their own results too).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from jarvis.alerts import AlertResult, AlertSink
from jarvis.core.guardrails import ActionRisk
from jarvis.logging import get_logger
from jarvis.notify.held import Held
from jarvis.notify.models import NotifySettings
from jarvis.notify.policy import Policy
from jarvis.notify.ports import Decision, Delivery, NotifyPolicy, Signal
from jarvis.notify.quiet import in_quiet
from jarvis.notify.store import NotifyStore
from jarvis.notify.storm import Storm, summary_text
from jarvis.tools.audit import AuditTrail

log = get_logger(__name__)
MAX_TEXT = 300


class PushSender(Protocol):
    async def send(self, uid: str, *, kind: str, text: str, silent: bool = False) -> int: ...


def _clean(text: str) -> str:
    one = " ".join("".join(c if c >= " " and c != "\x7f" else " " for c in text).split())
    return one if len(one) <= MAX_TEXT else one[: MAX_TEXT - 1].rstrip() + "..."


class NotifyService:
    def __init__(
        self,
        store: NotifyStore,
        audit: AuditTrail,
        *,
        telegram: AlertSink | None = None,
        push: PushSender | None = None,
        policy: NotifyPolicy | None = None,
        storm: Storm | None = None,
        timezone: str = "Asia/Kolkata",
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._audit = audit
        self._telegram = telegram
        self._push = push
        self._policy: NotifyPolicy = policy or Policy()
        self._storm = storm or Storm()
        self._tz = timezone
        self._now = now
        self._held = Held(store)

    @property
    def store(self) -> NotifyStore:
        return self._store

    async def settings(self, uid: str) -> NotifySettings:
        """The owner's settings. Unreadable settings never stop an alert: the defaults apply
        (burglar and hazard alerts ring), and nothing is written back."""
        try:
            got = await self._store.get(uid)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "notify: settings unreadable, defaults used", extra={"error": type(exc).__name__}
            )
            got = NotifySettings()
        return got.model_copy(update={"tz": self._tz})

    async def notify(
        self,
        uid: str,
        signal: Signal,
        message: str,
        *,
        named_message: str | None = None,
        photo: bytes | None = None,
    ) -> Delivery:
        now = self._now()
        settings = await self.settings(uid)
        await self._send_due_summary(uid, settings, now)
        decision = self._policy.decide(signal, settings, now)
        if decision.action == "drop":
            return await self._done(uid, signal, Delivery(action="drop", reason=decision.reason))
        if decision.action == "hold":
            return await self._hold(uid, signal, settings, decision, message, now)
        verdict = self._storm.admit(uid, signal, decision, now)
        if not verdict.admit:
            return await self._done(uid, signal, Delivery(action="drop", reason=verdict.reason))
        use_name = bool(named_message) and settings.names_in_alerts and not signal.child
        text = _clean(named_message if use_name and named_message else message)
        want_photo = (
            photo
            if photo is not None
            and signal.kind == "home_intruder"
            and decision.action == "ring"
            and settings.snapshot.on
            else None
        )
        return await self._done(
            uid, signal, await self._deliver(uid, signal, decision, text, want_photo)
        )

    async def _hold(
        self,
        uid: str,
        signal: Signal,
        settings: NotifySettings,
        decision: Decision,
        message: str,
        now: datetime,
    ) -> Delivery:
        try:
            await self._held.add(uid, signal, now)
        except Exception as exc:  # noqa: BLE001 - never lose an alert: ring it instead
            log.warning("notify: hold failed, ringing", extra={"error": type(exc).__name__})
            fallback = Decision(action="ring", reason="hold_failed", urgency=decision.urgency)
            return await self._done(
                uid, signal, await self._deliver(uid, signal, fallback, _clean(message), None)
            )
        return await self._done(uid, signal, Delivery(action="hold", reason=decision.reason))

    async def _deliver(
        self, uid: str, signal: Signal, decision: Decision, text: str, photo: bytes | None
    ) -> Delivery:
        silent = decision.action == "silent"
        results = await asyncio.gather(
            self._telegram_send(uid, signal, text, silent, photo),
            self._push_send(uid, signal, text, silent),
        )
        tg, pushed = results
        return Delivery(
            action=decision.action,
            reason=decision.reason,
            telegram=tg.sent,
            push=min(pushed, 5),
            photo_sent=bool(tg.sent and getattr(tg, "photo", False)),
        )

    async def _telegram_send(
        self, uid: str, signal: Signal, text: str, silent: bool, photo: bytes | None
    ) -> AlertResult:
        if self._telegram is None:
            return AlertResult(False, "not set up")
        try:
            return await self._telegram.send(
                uid, text, kind=signal.kind, silent=silent, photo=photo
            )
        except Exception as exc:  # noqa: BLE001 - contained
            log.warning("notify: telegram failed", extra={"error": type(exc).__name__})
            return AlertResult(False, "Telegram couldn't be reached")

    async def _push_send(self, uid: str, signal: Signal, text: str, silent: bool) -> int:
        if self._push is None:
            return 0
        try:
            return await self._push.send(uid, kind=signal.kind, text=text, silent=silent)
        except Exception as exc:  # noqa: BLE001 - contained
            log.warning("notify: push failed", extra={"error": type(exc).__name__})
            return 0

    async def _send_due_summary(self, uid: str, settings: NotifySettings, now: datetime) -> None:
        count = self._storm.due_summary(uid, now)
        if count:
            signal = Signal(source="home", kind="home_summary")
            decision = Decision(action="ring", reason="urgent", urgency="urgent")
            await self._done(
                uid, signal, await self._deliver(uid, signal, decision, summary_text(count), None)
            )

    async def flush_summaries(self) -> int:
        """Tick: storm summaries that are due for owners with no newer alert. Returns how many."""
        now = self._now()
        sent = 0
        for uid in self._storm.owners_with_pending():
            before = self._storm.owners_with_pending()
            await self._send_due_summary(uid, await self.settings(uid), now)
            sent += len(before) - len(self._storm.owners_with_pending())
        return sent

    async def flush_held(self, uid: str) -> bool:
        """When quiet hours are over, send the held alerts as ONE summary (kinds and counts)."""
        settings = await self.settings(uid)
        now = self._now()
        if in_quiet(now, settings.quiet, settings.tz):
            return False
        text = await self._held.flush(uid)
        if text is None:
            return False
        signal = Signal(source="home", kind="test")
        decision = Decision(action="ring", reason="held_summary", urgency="important")
        decision = decision.model_copy(
            update={"action": "silent" if settings.ring_for == "urgent" else "ring"}
        )
        await self._done(uid, signal, await self._deliver(uid, signal, decision, text, None))
        return True

    async def flush_all_held(self) -> int:
        sent = 0
        for uid in await self._store.held_owners():
            try:
                sent += int(await self.flush_held(uid))
            except Exception as exc:  # noqa: BLE001 - one owner's failure does not stop the rest
                log.warning("notify: flush failed", extra={"error": type(exc).__name__})
        return sent

    async def _done(self, uid: str, signal: Signal, delivery: Delivery) -> Delivery:
        try:
            await self._audit.append(
                agent="alerts",
                tool="notify_delivery",
                risk=ActionRisk.READ_ONLY,
                outcome=delivery.action,
                args={
                    "kind": signal.kind,
                    "reason": delivery.reason,
                    "telegram": delivery.telegram,
                    "push": delivery.push,
                    "photo": delivery.photo_sent,
                },
            )
        except Exception as exc:  # noqa: BLE001 - the alert already happened
            log.error("AUDIT WRITE FAILED for a delivery", extra={"error": type(exc).__name__})
        return delivery


__all__ = ["NotifyService", "PushSender"]
