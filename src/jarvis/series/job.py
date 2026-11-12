# src/jarvis/series/job.py
"""`series_checkin`: "did the session happen?" (R11.1 O2b; docs/plans/r11-1-observations.md D6).
A job on the helpers' 5-minute clock. No model, so it works the same in No-AI mode.

For each configured owner: every session that ended at least `ASK_AFTER` (15 minutes) and at
most `ASK_WITHIN` ago with no answer is asked about ONCE: a claim document is created in a
transaction before the alert goes out (`SeriesStore.claim`). The alert is the app's one notifier
with kind `series_checkin`: it rings by day and is HELD in quiet hours (never dropped); the text
is a fixed template (number, the plan's own name, time) and never a title. Before it is asked
the session's event is read once (`SeriesService.recheck`): one he deleted by hand is marked
removed and never asked; one he moved takes the new time and is asked after it. A question that did
not leave JARVIS is never counted as asked (as `notify.sink.result_of` reads a delivery): sent on
a channel is "asked", held for the night is "held" (it goes out in the morning); dropped by the
policy, a ring that reached no channel, a notifier that raised or a send that was cancelled is
"failed", and its claim is given back so a later run asks again. Older unanswered sessions are
not chased: they show in the console and in the brief's line. One session, one owner or the
part's set-up failing never stops the rest. Once a day the owner's old claims are swept.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, tzinfo
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jarvis.logging import get_logger
from jarvis.notify.ports import Delivery, Notifier, Signal
from jarvis.notify.sink import result_of
from jarvis.series.cards import QUESTION, question
from jarvis.series.models import Plan, PlanSession
from jarvis.series.service import ASK_AFTER, SeriesService
from jarvis.series.store import SeriesStore
from jarvis.series.words import told_key

log = get_logger(__name__)

NAME: Final = "series_checkin"
ASK_WITHIN = timedelta(hours=24)
MAX_PER_RUN = 3  # questions per owner in one run (the clock gives all helpers 20 s together)
SWEEP_EVERY = timedelta(hours=24)


def _zone(name: str) -> tzinfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


class CheckinJob:
    name = NAME
    budget_s = 8.0

    def __init__(
        self,
        svc: SeriesService,
        notifier: Callable[[], Notifier | None],
        *,
        now: Callable[[], datetime],
        tz: str,
        on_run: Callable[[], object] | None = None,
    ) -> None:
        self._svc, self._notifier, self._now = svc, notifier, now
        self._tz = _zone(tz)
        self._on_run = on_run  # the part's late set-up (its No-AI phrases), tried each run
        self._swept: dict[str, datetime] = {}

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        counts = {"asked": 0, "held": 0, "failed": 0}
        if self._on_run is not None:
            try:
                self._on_run()
            except Exception as exc:  # noqa: BLE001 - the set-up never stops the check-ins
                log.warning("plan set-up failed", extra={"error": type(exc).__name__})
        for uid in owners:
            try:
                await self._owner(uid, counts)
            except Exception as exc:  # noqa: BLE001 - one owner never stops the others
                log.warning("check-in failed for an owner", extra={"error": type(exc).__name__})
                counts["failed"] += 1
        return counts

    async def _owner(self, uid: str, counts: dict[str, int]) -> None:
        now, store = self._now(), self._svc.store
        due = [w for w in await self._svc.waiting(uid) if now - w.session.end <= ASK_WITHIN]
        for w in due[:MAX_PER_RUN]:
            try:
                how = await self._ask(store, uid, w.plan, w.session, now)
            except Exception as exc:  # noqa: BLE001 - one session never stops the others
                log.warning("a check-in failed", extra={"error": type(exc).__name__})
                how = "failed"
            if how:
                counts[how] += 1
        if now - self._swept.get(uid, datetime.min.replace(tzinfo=now.tzinfo)) >= SWEEP_EVERY:
            self._swept[uid] = now
            await store.sweep(uid, now)

    async def _ask(
        self, store: SeriesStore, uid: str, plan: Plan, s: PlanSession, now: datetime
    ) -> str:
        """ "asked" | "held" | "failed" | "" (already asked, or nobody to tell)."""
        notifier = self._notifier()
        if notifier is None:
            return ""
        key = told_key(plan, s)
        if await store.told(uid, key):  # asked already: nothing more is read
            return ""
        if await self._svc.recheck(uid, plan, s) in ("removed", "moved"):
            return ""  # he deleted or moved the event himself: never asked about the old one
        if not await store.claim(uid, key, now):
            return ""
        try:
            delivery = await notifier.notify(
                uid, Signal(source="nudge", kind=NAME), question(plan, s, self._tz)
            )
        except BaseException as exc:  # not sent (or cancelled): give the claim back first
            await _give_back(store, uid, key)
            if not isinstance(exc, Exception):
                raise
            log.warning("check-in not sent", extra={"error": type(exc).__name__})
            return "failed"
        how = _counted(delivery)
        if how == "failed":
            log.warning(
                "check-in reached nobody; it will be asked again",
                extra={"action": delivery.action, "reason": delivery.reason},
            )
            await _give_back(store, uid, key)
        return how


def _counted(delivery: Delivery) -> str:
    """How a delivery counts, as `notify.sink.result_of` reads it: sent, held, or not sent."""
    out = result_of(delivery)
    if out.sent:
        return "asked"
    return "held" if out.queued else "failed"


async def _give_back(store: SeriesStore, uid: str, key: str) -> None:
    """Release a claim so a later run asks; shielded from a cancellation, never raises."""
    try:
        await asyncio.shield(store.release(uid, key))
    except Exception as exc:  # noqa: BLE001 - logged: that session is then not asked again
        log.error(
            "a check-in claim was not given back; that session will not be asked again",
            extra={"error": type(exc).__name__},
        )


__all__ = ["ASK_AFTER", "ASK_WITHIN", "MAX_PER_RUN", "NAME", "QUESTION", "CheckinJob"]
