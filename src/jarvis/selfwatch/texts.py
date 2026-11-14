# src/jarvis/selfwatch/texts.py
"""What JARVIS says about itself (docs/plans/r14-hardening.md D5, D6), and how it says it.

Every alert is a FIXED template: job names (from the code), a time of day, the version and,
for the spend spike only, the rupee figure. Never a logger name, an exception's or a vendor's
text, or any other amount. At most `MAX_TEXT` characters (the notifier's message limit).

`Teller.tell(owners, kind, cause, text, now)`: per owner, the once-only claim first
(`ledger.Told`), then the send with `ports.SENDING` set (so the errors handler leaves out what
the notifier and Telegram log meanwhile). A send that fails is logged as a class name and never
raised: it is not a job failure, and the claim keeps it from being tried again in a loop.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Literal

from jarvis.alerts import AlertKind
from jarvis.logging import get_logger
from jarvis.notify.ports import Notifier, Signal
from jarvis.selfwatch.ledger import Told
from jarvis.selfwatch.ports import SENDING

log = get_logger(__name__)

MAX_TEXT = 300
MAX_NAMED = 8  # job names in one message; the rest are counted
Clock = Literal["tick", "watchdog"]
CLOCK_WORDS: dict[str, str] = {
    "watchdog": "JARVIS's 5-minute clock",
    "tick": "JARVIS's morning clock",
}


def _fit(text: str) -> str:
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1].rstrip() + "…"


def job_failing(names: Sequence[str]) -> str:
    n = len(names)
    shown = ", ".join(names[:MAX_NAMED])
    more = f" and {n - MAX_NAMED} more" if n > MAX_NAMED else ""
    noun = "background job keeps" if n == 1 else "background jobs keep"
    return _fit(f"{n} {noun} failing: {shown}{more}. JARVIS will say when it works again.")


def jobs_back() -> str:
    return "JARVIS's background jobs are working again."


def clock_stopped(clock: Clock, at: str) -> str:
    if clock == "tick":
        return (
            f"{CLOCK_WORDS['tick']} did not run today by {at}. The brief and the daily checks "
            "wait until it runs; check JARVIS's jobs in Cloud Scheduler."
        )
    return (
        f"{CLOCK_WORDS['watchdog']} has not run since {at}. Reminders and checks wait until it "
        "runs; check JARVIS's jobs in Cloud Scheduler."
    )


def clock_back(clock: Clock) -> str:
    return f"{CLOCK_WORDS[clock]} is running again."


def brief_missed(by: str) -> str:
    return f"Today's morning brief wasn't made by {by}. Open JARVIS to make it now."


def errors_piling(threshold: int) -> str:
    return (
        f"JARVIS logged more than {threshold} errors in an hour. Open Vitals and run a "
        "systems check, or tell the Workshop."
    )


def spend_spike(inr: float, factor: float) -> str:
    return (
        f"JARVIS's AI spend in the last day was ₹{inr:,.0f}, over {factor:g} times a usual day. "
        "Open Vitals to see where it went."
    )


def deploy_changed(version: str) -> str:
    return f"JARVIS was updated: version {version[:20]} is now live."


class Teller:
    """Claim, then send, once per owner, kind and cause."""

    def __init__(self, notifier: Callable[[], Notifier | None], told: Told) -> None:
        self._notifier = notifier
        self._told = told

    async def tell(
        self,
        owners: Sequence[str],
        kind: AlertKind,
        cause: str,
        text: str,
        now: datetime,
        *,
        subject: str | None = None,
    ) -> int:
        """How many owners it was sent to (a claimed but failed send counts 0)."""
        notifier = self._notifier()
        if notifier is None:
            return 0
        sent = 0
        for uid in owners:
            if not await self._told.claim(uid, kind, cause, now):
                continue
            sent += await self._send(
                notifier, uid, Signal(source="system", kind=kind, subject=subject), _fit(text)
            )
        return sent

    @staticmethod
    async def _send(notifier: Notifier, uid: str, signal: Signal, text: str) -> int:
        token = SENDING.set(True)
        try:
            await notifier.notify(uid, signal, text)
        except Exception as exc:  # noqa: BLE001 - a failed send is not a job failure
            log.warning(
                "selfwatch alert not sent", extra={"kind": signal.kind, "error": type(exc).__name__}
            )
            return 0
        finally:
            SENDING.reset(token)
        return 1


__all__ = [
    "CLOCK_WORDS",
    "MAX_TEXT",
    "Teller",
    "brief_missed",
    "clock_back",
    "clock_stopped",
    "deploy_changed",
    "errors_piling",
    "job_failing",
    "jobs_back",
    "spend_spike",
]
