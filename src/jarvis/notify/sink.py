# src/jarvis/notify/sink.py
"""`PolicyAlerts`: the `AlertSink` the rest of JARVIS calls (R3 D10: every alert goes through the
policy). At I1 `app.state.alerts` becomes this, wrapping Telegram and Web Push through
`NotifyService`, so R1's and R2's alerts get quiet hours too. Callers keep the same contract: it
never raises for "can't send"; it returns an `AlertResult` with a short reason."""

from __future__ import annotations

from jarvis.alerts import AlertKind, AlertResult
from jarvis.notify.ports import Delivery, Notifier, Signal, SignalSource

_WHY = {
    "quiet_hours": "held until quiet hours end",
    "feed_only": "kept in your feed only",
    "switched_off": "switched off for this kind of alert",
    "storm": "grouped into a summary",
    "package_gap": "too soon after the last one",
    "greeting_gap": "too soon after the last one",
}


def result_of(delivery: Delivery) -> AlertResult:
    if delivery.telegram or delivery.push:
        return AlertResult(sent=True)
    if delivery.action in {"drop", "hold"}:
        return AlertResult(sent=False, reason=_WHY.get(delivery.reason, "not sent"))
    return AlertResult(sent=False, reason="no channel could deliver it")


class PolicyAlerts:
    def __init__(self, notifier: Notifier, *, source: SignalSource = "nudge") -> None:
        self._notifier = notifier
        self._source = source

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
            delivery = await self._notifier.notify(
                uid, Signal(source=self._source, kind=kind), text, photo=photo
            )
        except Exception:  # noqa: BLE001 - an alert port never raises for "can't send"
            return AlertResult(sent=False, reason="alerts couldn't be sent just now")
        return result_of(delivery)


__all__ = ["PolicyAlerts", "result_of"]
