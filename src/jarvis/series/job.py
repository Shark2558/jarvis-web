# src/jarvis/series/job.py
"""`series_checkin`: "did the session happen?" (R11.1 O2b; docs/plans/r11-1-observations.md D6).
A job on the helpers' 5-minute clock. No model, so it works the same in No-AI mode.

For each configured owner: every session that ended at least `ASK_AFTER` (15 minutes) and at
most `ASK_WITHIN` ago with no answer is asked about ONCE: a claim document is created in a
transaction before the alert goes out (`SeriesStore.claim`). The alert is the app's one notifier
with kind `series_checkin`: it rings by day and is HELD in quiet hours (never dropped); the text
is a fixed template (number, the plan's own name, time) and never a title. If the notifier fails,
the claim is given back so a later run asks; older unanswered sessions are not chased: they show
in the console and in the brief's line. Once a day the owner's old claims are swept.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jarvis.logging import get_logger
from jarvis.notify.ports import Notifier, Signal
from jarvis.series.cards import QUESTION, question
from jarvis.series.models import Plan, PlanSession
from jarvis.series.service import ASK_AFTER, SeriesService
from jarvis.series.store import SeriesStore
from jarvis.series.words import told_key

log = get_logger(__name__)

NAME = "series_checkin"
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
            self._on_run()
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
            how = await self._ask(store, uid, w.plan, w.session, now)
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
        if not await store.claim(uid, key, now):
            return ""
        try:
            delivery = await notifier.notify(
                uid, Signal(source="nudge", kind=NAME), question(plan, s, self._tz)
            )
        except Exception as exc:  # noqa: BLE001 - not sent: give the claim back, try later
            log.warning("check-in not sent", extra={"error": type(exc).__name__})
            await store.release(uid, key)
            return "failed"
        return "held" if delivery.action == "hold" else "asked"


__all__ = ["ASK_AFTER", "ASK_WITHIN", "MAX_PER_RUN", "NAME", "QUESTION", "CheckinJob"]
