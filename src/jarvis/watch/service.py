# src/jarvis/watch/service.py
"""The watch and sleep service (docs/plans/r7-mobile.md D17, D18): the `health` door's intake,
last night, the week, today's sums, a night he typed, the Watch tab's view and the brief's line.
Every sentence is a fixed template (`jarvis.watch.words`); nothing here calls a model.

- `intake(uid, body)`: the body checked whole (`models.parse_health`, his calendar's today), then
  kept sealed; `IntakeRefused` / `WatchOff` / `WatchUnavailable` otherwise.
- `night(uid, day)`: the night that ended on `day` (`sleep.last_night`), from that day's sessions
  and the day before's (the phone may file a night under its start), or a night he typed.
- `note(uid, start, end)`: "HH:MM" to "HH:MM", his own words; the night ends on today when its
  end has come, else yesterday; 30 minutes to 20 hours, ending by 14:00 (else `NoteRefused`).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from jarvis.config import Settings
from jarvis.logging import get_logger
from jarvis.watch.models import (
    TYPED_WRITER,
    IntakeRefused,
    Session,
    StoredDay,
    parse_health,
    source_of,
)
from jarvis.watch.sleep import LATEST_END, Night, Week, last_night, week
from jarvis.watch.store import WatchState, WatchStore

log = get_logger(__name__)
WEEK_DAYS = 7
NOTE_MIN, NOTE_MAX = 30, 20 * 60  # minutes a typed night may last
_HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


class NoteRefused(ValueError):
    BAD = 'That sleep time doesn\'t look right, Sir: say it like "I slept 11:30 to 6".'
    NAP = "That reads as a nap, Sir: I keep the night's sleep only, ending by 14:00."

    def __init__(self, words: str = BAD) -> None:
        super().__init__(words)


def _utc(now: Callable[[], datetime]) -> datetime:
    at = now()
    return at if at.tzinfo is not None else at.replace(tzinfo=UTC)


def _hhmm(text: str) -> time:
    m = _HHMM.fullmatch(text.strip()) if isinstance(text, str) else None
    if m is None:
        raise NoteRefused()
    return time(int(m[1]), int(m[2]))


class WatchService:
    def __init__(self, store: WatchStore, s: Settings, *, now: Callable[[], datetime]) -> None:
        self._store = store
        self._s = s
        self._now = now

    @property
    def enabled(self) -> bool:
        return bool(self._s.watch_enabled)

    @property
    def sealed(self) -> bool:
        return self._store.sealed

    @property
    def store(self) -> WatchStore:
        return self._store

    def zone(self) -> tzinfo:
        try:
            return ZoneInfo(self._s.user_timezone)
        except (KeyError, ValueError):
            return UTC

    def local_now(self) -> datetime:
        return _utc(self._now).astimezone(self.zone())

    def today(self) -> date:
        return self.local_now().date()

    # ---- the door ---------------------------------------------------------------------------
    async def intake(self, uid: str, body: bytes) -> int:
        try:
            parsed = parse_health(body, self.today())
        except IntakeRefused:
            if self.sealed:
                await self._store.note_refused(uid)  # a phone whose syncs are all refused is told
            raise
        return await self._store.put(uid, parsed.days)

    # ---- reading ----------------------------------------------------------------------------
    async def _pair(self, uid: str, day: date) -> tuple[list[Session], Session | None]:
        got = await self._store.days(uid, [day - timedelta(days=1), day])
        sessions = [x for d in got.values() for x in d.sleep]
        here = got.get(day)
        return sessions, here.typed if here is not None else None

    async def night(self, uid: str, day: date) -> Night | None:
        sessions, typed = await self._pair(uid, day)
        return last_night(day, sessions, typed)

    async def week(self, uid: str, day: date) -> Week | None:
        dates = [day - timedelta(days=i) for i in range(WEEK_DAYS + 1)]
        got = await self._store.days(uid, dates)
        nights = []
        for i in range(WEEK_DAYS):
            d = day - timedelta(days=i)
            sessions = [x for k in (d, d - timedelta(days=1)) if k in got for x in got[k].sleep]
            typed = got[d].typed if d in got else None
            n = last_night(d, sessions, typed)
            if n is not None:
                nights.append(n)
        return week(nights)

    async def day(self, uid: str, d: date) -> StoredDay | None:
        return await self._store.day(uid, d)

    async def state(self, uid: str) -> WatchState:
        return await self._store.state(uid)

    # ---- a night he typed ---------------------------------------------------------------------
    async def note(self, uid: str, start: str, end: str) -> Night:
        a, b = _hhmm(start), _hhmm(end)
        if b > LATEST_END:
            raise NoteRefused(NoteRefused.NAP)
        now = self.local_now()
        day = now.date() if b <= now.time() else now.date() - timedelta(days=1)
        zone = self.zone()
        ended = datetime.combine(day, b, tzinfo=zone)
        began_on = day if a < b else day - timedelta(days=1)
        began = datetime.combine(began_on, a, tzinfo=zone)
        minutes = (ended - began).total_seconds() / 60
        if not NOTE_MIN <= minutes <= NOTE_MAX:
            raise NoteRefused()
        typed = Session(start=began.isoformat(), end=ended.isoformat(), writer=TYPED_WRITER)
        await self._store.set_typed(uid, day, typed)
        log.info("a typed night was kept")
        night = last_night(day, [], typed)
        if night is None:  # it ends on `day` by 14:00, checked above: never in practice
            raise NoteRefused()
        return night

    # ---- the Watch tab ----------------------------------------------------------------------
    async def view(self, uid: str) -> dict[str, Any]:
        today = self.today()
        state = await self._store.state(uid)
        day = await self._store.day(uid, today)
        night = await self.night(uid, today)
        wk = await self.week(uid, today)
        return {
            "enabled": self.enabled,
            "sealed": self.sealed,
            "last_synced": state.last_sync.isoformat() if state.last_sync else None,
            "kinds": dict(state.kinds),
            "today": _today_view(day),
            "last_night": _night_view(night),
            "week": None
            if wk is None
            else {
                "nights": wk.nights,
                "avg_minutes": wk.avg_minutes,
                "bed_from": wk.bed_from,
                "bed_to": wk.bed_to,
            },
        }


def _today_view(day: StoredDay | None) -> dict[str, Any] | None:
    if day is None or (day.steps is None and day.heart is None):
        return None
    steps = heart = None
    if day.steps is not None:
        steps = {"count": day.steps.count, "source": source_of(day.steps.writer)}
    if day.heart is not None:
        h = day.heart
        heart = {"min": h.min, "avg": h.avg, "max": h.max, "source": source_of(h.writer)}
    return {"steps": steps, "heart": heart}


def _night_view(night: Night | None) -> dict[str, Any] | None:
    if night is None:
        return None
    stages = night.stages.model_dump() if night.stages is not None else None
    return {
        "minutes": night.minutes,
        "start": night.start,
        "end": night.end,
        "source": night.source,
        "stages": stages,
    }


__all__ = ["NoteRefused", "WatchService"]
