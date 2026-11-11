# src/jarvis/helpers/nudges/calendar.py
"""What Part C reads from outside: his calendar (items 8's meeting variant, 11 and 12) and, for the
free-time pick, whether rain is likely (D12, Part B's weather).

- `CalendarSource`: today's events as `CalEvent`s. `GoogleCalendar` reads his PRIMARY calendar
  through the Google connector, single events with a start time only (all-day ones block nothing),
  each call capped at `sources.OUTSIDE_TIMEOUT_S`. An event's title is used only to match his own
  words in code; it is never put in a message, a log or a stored document (`key` is a fingerprint
  of the event's id).
- `Agenda`: one fetch per owner at most every `REFRESH` (a failure is remembered `RETRY_AFTER`),
  and only when a nudge that needs it is due, so the 5-minute clock stays light. Every fetch first
  asks his permission row (`calendar_list_events`, read-only; a rule that can't be read = no fetch,
  fail closed) and leaves one audit line (agent `helpers`, the tool name and the outcome, no
  words).
- `RainSource`: `rain_likely(uid, start, end) -> bool | None` (None: unknown). Part C has none of
  its own; I1 joins Part B's weather (INTEGRATION-C.md, "Needs I1").
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from jarvis.core.guardrails import ActionRisk
from jarvis.helpers.sources import OUTSIDE_TIMEOUT_S
from jarvis.logging import get_logger
from jarvis.tools.audit import AuditTrail
from jarvis.tools.policy import Effect, OwnerRules, Policy
from jarvis.tools.provenance import is_owner_authored_event

log = get_logger(__name__)

EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
CALENDAR_TOOL = "calendar_list_events"  # the row his background reads obey (calendar_read)
MAX_EVENTS = 50
REFRESH = timedelta(minutes=30)
RETRY_AFTER = timedelta(minutes=10)
AUDIT_AGENT = "helpers"


@dataclass(frozen=True)
class CalEvent:
    key: str  # a fingerprint of the event id: what claims and check-ins are kept by
    title: str  # matched in code only; never sent, logged or stored
    start: datetime
    end: datetime
    own: bool  # only he (or JARVIS for him) wrote it: his own plan


@runtime_checkable
class CalendarSource(Protocol):
    async def events(self, uid: str, start: datetime, end: datetime) -> list[CalEvent]: ...


@runtime_checkable
class RainSource(Protocol):
    async def rain_likely(self, uid: str, start: datetime, end: datetime) -> bool | None: ...


def fingerprint(event_id: str) -> str:
    return hashlib.sha256(f"r11-nudges/{event_id}".encode()).hexdigest()[:16]


def _when(raw: Any) -> datetime | None:
    value = raw.get("dateTime") if isinstance(raw, dict) else None
    if not isinstance(value, str):
        return None  # an all-day event: it blocks no time and isn't a planned activity
    try:
        at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo is not None else at.replace(tzinfo=UTC)


def to_event(item: Any) -> CalEvent | None:
    if not isinstance(item, dict) or item.get("status") == "cancelled":
        return None
    start, end, ident = _when(item.get("start")), _when(item.get("end")), item.get("id")
    if start is None or end is None or end <= start or not isinstance(ident, str):
        return None
    title = str(item.get("summary") or "")[:200]
    return CalEvent(fingerprint(ident), title, start, end, is_owner_authored_event(item))


class GoogleCalendar:
    def __init__(self, google: Any) -> None:
        self._google = google

    async def events(self, uid: str, start: datetime, end: datetime) -> list[CalEvent]:
        params = {
            "timeMin": start.astimezone(UTC).isoformat(),
            "timeMax": end.astimezone(UTC).isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": MAX_EVENTS,
        }
        call = self._google.request(uid, "GET", EVENTS_URL, params=params)
        data = await asyncio.wait_for(call, OUTSIDE_TIMEOUT_S)
        items = data.get("items") if isinstance(data, dict) else None
        found = (to_event(i) for i in (items if isinstance(items, list) else [])[:MAX_EVENTS])
        return [e for e in found if e is not None]


Allowed = Callable[[str], Awaitable[bool]]


def row_allows(permissions: Callable[[], OwnerRules | None]) -> Allowed:
    """His calendar row decides a background read (Never = no read); unreadable = no read."""

    async def allowed(uid: str) -> bool:
        rules_of = permissions()
        if rules_of is None:
            return True
        try:
            rules = await rules_of.rules_for(uid)
        except Exception as exc:  # noqa: BLE001 - fail closed: no read this run
            log.warning("permissions unreadable for nudges", extra={"error": type(exc).__name__})
            return False
        return Policy(rules).decide(CALENDAR_TOOL, ActionRisk.READ_ONLY, {}) is not Effect.DENY

    return allowed


@dataclass
class _Cached:
    at: datetime
    events: list[CalEvent] | None


class Agenda:
    """Today's events per owner, fetched only when asked and at most every `REFRESH`."""

    def __init__(
        self,
        source: CalendarSource | None,
        *,
        allowed: Allowed,
        audit: AuditTrail,
        now: Callable[[], datetime],
    ) -> None:
        self._source = source
        self._allowed = allowed
        self._audit = audit
        self._now = now
        self._cache: dict[tuple[str, str], _Cached] = {}

    @property
    def linked(self) -> bool:
        return self._source is not None

    async def today(self, uid: str, start: datetime, end: datetime) -> list[CalEvent] | None:
        """Events between `start` and `end` (his local day); None: no calendar, or not now."""
        if self._source is None:
            return None
        key, now = (uid, start.isoformat()), self._now()
        got = self._cache.get(key)
        if got is not None:
            wait = REFRESH if got.events is not None else RETRY_AFTER
            if now - got.at < wait:
                return got.events
        events = await self._fetch(uid, start, end)
        self._cache = {k: v for k, v in self._cache.items() if k[0] != uid}  # one day per owner
        self._cache[key] = _Cached(now, events)
        return events

    def forget(self, uid: str) -> None:
        self._cache = {k: v for k, v in self._cache.items() if k[0] != uid}

    async def _fetch(self, uid: str, start: datetime, end: datetime) -> list[CalEvent] | None:
        assert self._source is not None
        if not await self._allowed(uid):
            await self._note("denied")
            return None
        try:
            events = await self._source.events(uid, start, end)
        except Exception as exc:  # noqa: BLE001 - no calendar this run; the class in the log
            log.warning("nudges: calendar not read", extra={"error": type(exc).__name__})
            await self._note("failed")
            return None
        await self._note("read")
        return list(events)

    async def _note(self, outcome: str) -> None:
        try:
            await self._audit.append(
                agent=AUDIT_AGENT,
                tool=CALENDAR_TOOL,
                risk=ActionRisk.READ_ONLY,
                outcome=outcome,
                args={},
                detail="nudges",
            )
        except Exception as exc:  # noqa: BLE001 - the audit is append-only; never fail a nudge
            log.warning("nudges: audit not written", extra={"error": type(exc).__name__})


__all__ = [
    "CALENDAR_TOOL",
    "REFRESH",
    "Agenda",
    "Allowed",
    "CalEvent",
    "CalendarSource",
    "GoogleCalendar",
    "RainSource",
    "fingerprint",
    "row_allows",
    "to_event",
]
