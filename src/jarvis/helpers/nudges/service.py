# src/jarvis/helpers/nudges/service.py
"""Part C's one service (docs/plans/r11-free-helpers.md D3, D4, D6): what the clock jobs, the tools,
the routes, the privacy row and the brief share.

`deliver` is the only way a nudge goes out: it CLAIMS the nudge's key for the day in a transaction
(`NudgeStore.claim`), then composes the text (which may read his calendar, his pending items or
the sealed log), then sends through the part's own sender (`ctx.sender`, the gate: caps, snooze,
stop, the night rule), and RELEASES the claim when no channel took the message
(`SendResult.retry`) or the text couldn't be made yet (`NotNow`), so the next run tries again.
Anything else keeps the claim: never twice, never early (the planners only offer a nudge whose
due time has come).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from jarvis.helpers.gate import GateStore, PartSender
from jarvis.helpers.kinds import NudgeKind
from jarvis.helpers.nudges.calendar import Agenda, CalEvent, RainSource
from jarvis.helpers.nudges.models import NudgeSettings
from jarvis.helpers.nudges.schedule import local_day, zone
from jarvis.helpers.nudges.store import NudgeStore, WellbeingStore
from jarvis.helpers.ports import PendingItem, PendingSource
from jarvis.logging import get_logger

log = get_logger(__name__)

PENDING_TIMEOUT_S = 3.0
Compose = Callable[[], Awaitable[str | None]]
RainLookup = Callable[[], RainSource | None]


class NotNow(RuntimeError):
    """The text can't be made this run (the calendar didn't answer): release, try the next run."""


@dataclass(frozen=True)
class Plan:
    """A nudge whose time has come: its kind, its claim key, its due time and how to word it."""

    kind: NudgeKind
    key: str
    due: datetime
    compose: Compose


def fixed(text: str) -> Compose:
    async def words() -> str:
        return text

    return words


def minute_key(kind: str, due: datetime) -> str:
    return f"{kind}@{due.strftime('%Y-%m-%dT%H:%MZ')}"


class NudgeService:
    def __init__(
        self,
        *,
        store: NudgeStore,
        well: WellbeingStore,
        gate: GateStore,
        sender: PartSender,
        agenda: Agenda,
        rain: RainLookup,
        pending: Callable[[], tuple[PendingSource, ...]],
        tz: str,
        now: Callable[[], datetime],
    ) -> None:
        self.store = store
        self.well = well
        self.gate = gate
        self.sender = sender
        self.agenda = agenda
        self._rain = rain
        self._pending = pending
        self.tz = tz
        self.now = now

    @property
    def zone(self) -> ZoneInfo:
        return zone(self.tz)

    def day_of(self, at: datetime | None = None) -> date:
        return local_day(at or self.now(), self.tz)

    def bounds(self, day: date) -> tuple[datetime, datetime]:
        start = datetime(day.year, day.month, day.day, tzinfo=self.zone)
        return start, start + timedelta(days=1)

    async def events(self, uid: str, at: datetime) -> list[CalEvent] | None:
        start, end = self.bounds(self.day_of(at))
        return await self.agenda.today(uid, start, end)

    async def rain_likely(self, uid: str, start: datetime, end: datetime) -> bool | None:
        source = self._rain()
        if source is None:
            return None
        try:
            return await asyncio.wait_for(source.rain_likely(uid, start, end), PENDING_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 - unknown weather: no rain rule
            log.warning("nudges: rain unknown", extra={"error": type(exc).__name__})
            return None

    async def pending(self, uid: str, now: datetime) -> list[PendingItem]:
        """Every part's pending items (Part A's included), each source bounded; a slow or failing
        source is left out (logged by class name)."""
        out: list[PendingItem] = []
        for src in self._pending():
            try:
                got = await asyncio.wait_for(src.pending(uid, now), PENDING_TIMEOUT_S)
            except Exception as exc:  # noqa: BLE001 - one source never stops the focus nudge
                log.warning("nudges: a pending source failed", extra={"error": type(exc).__name__})
                continue
            out.extend(i for i in got if isinstance(i, PendingItem))
        return out

    async def settings(self, uid: str) -> NudgeSettings:
        return await self.store.settings(uid)

    async def deliver(self, uid: str, plan: Plan) -> str:
        """Claim, compose, send, release on retry. The outcome word (never the text)."""
        day = self.day_of(plan.due).isoformat()
        if not await self.store.claim(uid, day, plan.key):
            return "claimed"
        try:
            text = await plan.compose()
        except NotNow:
            await self.store.release(uid, day, plan.key)
            return "later"
        except Exception:
            await self.store.release(uid, day, plan.key)
            raise
        if text is None:
            return "nothing"  # nothing to say this time (no free gap, nothing pending): kept
        try:
            got = await self.sender.send(uid, plan.kind, text, due=plan.due)
        except Exception:
            await self.store.release(uid, day, plan.key)
            raise
        if got.retry:
            await self.store.release(uid, day, plan.key)
        return got.outcome


__all__ = [
    "PENDING_TIMEOUT_S",
    "Compose",
    "NotNow",
    "NudgeService",
    "Plan",
    "RainLookup",
    "fixed",
    "minute_key",
]
