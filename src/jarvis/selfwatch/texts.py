# src/jarvis/selfwatch/texts.py
"""What JARVIS says about itself (docs/plans/r14-hardening.md D5, D6), and how it says it.

Every alert is a FIXED template: job names (from the code), a time of day, the version and,
for the spend spike only, the rupee figure. Never a logger name, an exception's or a vendor's
text, or any other amount. At most `MAX_TEXT` characters (the notifier's message limit).

`Teller.tell(owners, kind, cause, text, now) -> Said`: per owner, the once-only claim first
(`ledger.Told`), then the send with `ports.SENDING` set (so the errors handler leaves out what
the notifier and Telegram log meanwhile). It reads the notifier's `Delivery` as Home's
`watchdog.took` does for its idle alert: told when a channel took it, when it was held for the
morning summary, or when it was dropped by the owner's own choice (`SETTLED`). Anything else
(a storm cap, no channel, a send that raised or was cancelled) reached nobody: its claim is
given back and `Said.settled` is False, so the caller commits nothing and the alert is raised
again. It is tried again at most every `RETRY_EVERY` (the storm's own gap, so a capped kind
is admitted then) and `MAX_TRIES` times in all; then the claim stands (a dead channel never
makes it try every 5 minutes for ever). Every retry passes the storm again, so none rings past
the self-health cap. A failed send is logged as a class name and never raised.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from jarvis.alerts import AlertKind
from jarvis.logging import get_logger
from jarvis.notify.ports import Delivery, Notifier, Signal
from jarvis.notify.storm import SELF_GAP
from jarvis.selfwatch.ledger import MAX_MEMORY_CLAIMS, Told
from jarvis.selfwatch.ports import SENDING

log = get_logger(__name__)

MAX_TEXT = 300
# The owner's own choice for the kind (`home.watchdog.OWNER_SETTLED`): nothing to retry.
SETTLED = frozenset({"switched_off", "feed_only"})
RETRY_EVERY = SELF_GAP  # 30 minutes: the storm admits the same kind and subject again by then
MAX_TRIES = 6  # about 2.5 hours of tries; then the claim stands
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


@dataclass(frozen=True)
class Said:
    """What a `tell` did: `sent` owners a channel took it for (or held it); `settled` when
    nothing is left to try (each owner told, held, his own choice, told before, or given up)."""

    sent: int = 0
    settled: bool = True


def reached(got: object) -> bool:
    """Whether the owner has it, or chose not to (`home.watchdog.took` for an idle alert)."""
    if not isinstance(got, Delivery):
        return False
    if got.telegram or got.push or got.action == "hold":
        return True
    return got.action == "drop" and got.reason in SETTLED


class Teller:
    """Claim, then send, once per owner, kind and cause; a send that reached nobody is retried."""

    def __init__(self, notifier: Callable[[], Notifier | None], told: Told) -> None:
        self._notifier = notifier
        self._told = told
        self._tries: dict[str, tuple[int, datetime]] = {}  # claim key -> (failed tries, next)
        self._quiet = False  # "no notifier" already logged

    async def tell(
        self,
        owners: Sequence[str],
        kind: AlertKind,
        cause: str,
        text: str,
        now: datetime,
        *,
        subject: str | None = None,
    ) -> Said:
        notifier = self._notifier()
        if notifier is None:
            if not self._quiet:
                log.warning("selfwatch alert waits: no notifier yet", extra={"kind": kind})
                self._quiet = True
            return Said(0, settled=False)
        signal = Signal(source="system", kind=kind, subject=subject)
        sent, settled = 0, bool(owners)
        for uid in owners:
            one, done = await self._one(notifier, uid, signal, cause, _fit(text), now)
            sent, settled = sent + one, settled and done
        return Said(sent, settled)

    async def _one(
        self, notifier: Notifier, uid: str, signal: Signal, cause: str, text: str, now: datetime
    ) -> tuple[int, bool]:
        """(sent, settled) for one owner."""
        key, kind = Told.key(uid, signal.kind, cause), signal.kind
        tries, due = self._tries.get(key, (0, now))
        if now < due:
            return 0, False  # its retry time has not come
        if not await self._told.claim(uid, kind, cause, now):
            return 0, True  # told before (here, by another process, or given up)
        try:
            got = await self._send(notifier, uid, signal, text)
        except BaseException:
            self._told.forget(uid, kind, cause)  # cancelled mid-send: tried again
            raise
        if isinstance(got, Delivery) and reached(got):
            self._tries.pop(key, None)
            return int(bool(got.telegram or got.push or got.action == "hold")), True
        reason = got.reason if isinstance(got, Delivery) else "error"
        extra = {"kind": kind, "reason": reason, "tries": tries + 1}
        if tries + 1 >= MAX_TRIES:
            self._tries.pop(key, None)
            log.warning("selfwatch alert given up", extra=extra)
            return 0, True  # the claim stands
        self._remember(key, tries + 1, now + RETRY_EVERY)
        await self._told.release(uid, kind, cause)
        log.warning("selfwatch alert not delivered, tried again later", extra=extra)
        return 0, False

    def _remember(self, key: str, tries: int, due: datetime) -> None:
        if key not in self._tries and len(self._tries) >= MAX_MEMORY_CLAIMS:
            del self._tries[min(self._tries, key=lambda k: self._tries[k][1])]
        self._tries[key] = (tries, due)

    @staticmethod
    async def _send(notifier: Notifier, uid: str, signal: Signal, text: str) -> Delivery | None:
        token = SENDING.set(True)
        try:
            return await notifier.notify(uid, signal, text)
        except Exception as exc:  # noqa: BLE001 - a failed send is not a job failure
            log.warning(
                "selfwatch alert not sent", extra={"kind": signal.kind, "error": type(exc).__name__}
            )
            return None
        finally:
            SENDING.reset(token)


__all__ = [
    "CLOCK_WORDS",
    "MAX_TEXT",
    "MAX_TRIES",
    "RETRY_EVERY",
    "SETTLED",
    "Said",
    "Teller",
    "brief_missed",
    "clock_back",
    "clock_stopped",
    "deploy_changed",
    "errors_piling",
    "job_failing",
    "jobs_back",
    "reached",
    "spend_spike",
]
