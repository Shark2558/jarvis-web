# src/jarvis/tools/google_calendar.py
"""Google Calendar tools (Layer 5/6, Task & Productivity) over the REST connector.

Risk classes: list/free-slots R1; create R2 alone but R3 once attendees are invited (an invite
is mail to other people — `Tool.risk_for`); update R2 for an event only the owner is on, R3 when
the event already has other attendees or the attendees change (decided by the `preview` look-up,
which also fills the approval card with the event's real title, time and every change); delete
R3, with the event looked up first for the card. A look-up that fails is fail-closed: no card,
no change. Times are ISO 8601; a naive time is read in the owner's calendar time zone, and every
time returned carries an offset.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jarvis.core.guardrails import ActionRisk
from jarvis.integrations.google import GoogleAPIError, GoogleConnector
from jarvis.logging import get_logger
from jarvis.tools.addresses import MAX_RECIPIENTS, loose_address, parse_address
from jarvis.tools.base import Preview, Tool
from jarvis.tools.calendar_cards import create_card, delete_card, others_on, update_card
from jarvis.tools.card import one_line
from jarvis.tools.context import require_tool_context
from jarvis.tools.external import wrap_external

log = get_logger(__name__)

BASE = "https://www.googleapis.com/calendar/v3"
EVENTS_URL = f"{BASE}/calendars/primary/events"
FREEBUSY_URL = f"{BASE}/freeBusy"
TZ_URL = f"{BASE}/users/me/calendarList/primary"
MAX_EVENTS = 50
MAX_SLOTS = 20
DESCRIPTION_LIMIT = 2_000
MAX_LISTED_ATTENDEES = 50
LINK_LIMIT = 500
DEFAULT_WORKING_HOURS = "09:00-18:00"

_EVENT_ID = re.compile(r"^[A-Za-z0-9_@.\-]{1,1024}$")
_HOURS = re.compile(r"^(\d{2}):(\d{2})-(\d{2}):(\d{2})$")

_ISO = {"type": "string", "description": "ISO 8601 date-time, e.g. 2027-01-15T09:00:00+05:30"}
_ATTENDEES = {
    "type": "array",
    "items": {"type": "string"},
    "description": "Email addresses to invite. Inviting people sends them mail: owner confirms.",
}


# ---- time helpers -------------------------------------------------------------------------


def parse_when(value: Any, tz: ZoneInfo, *, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an ISO 8601 string")
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{name} must be ISO 8601 (e.g. 2027-01-15T09:00:00+05:30)") from None
    return dt.replace(tzinfo=tz) if dt.tzinfo is None else dt.astimezone(tz)


def parse_window(args: dict[str, Any], tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = parse_when(args.get("start"), tz, name="start")
    end = parse_when(args.get("end"), tz, name="end")
    if end <= start:
        raise ValueError("end must be after start (start must come before end)")
    return start, end


def parse_working_hours(value: Any) -> tuple[time, time]:
    m = _HOURS.fullmatch(str(value or DEFAULT_WORKING_HOURS))
    if not m:
        raise ValueError("working_hours must look like HH:MM-HH:MM")
    h1, m1, h2, m2 = (int(x) for x in m.groups())
    try:
        a, b = time(h1, m1), time(h2, m2)
    except ValueError:
        raise ValueError("working_hours must look like HH:MM-HH:MM") from None
    if b <= a:
        raise ValueError("working_hours end must be after its start")
    return a, b


def _validate_attendees(raw: Any) -> list[str]:
    """Invitees get mail from Google, so they pass the same strict addr-spec check as mail
    recipients (normalised, IDN domains as punycode, duplicates dropped)."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("attendees must be a list of email addresses")
    if len(raw) > MAX_RECIPIENTS:
        raise ValueError(f"too many attendees (at most {MAX_RECIPIENTS})")
    emails: list[str] = []
    bad: list[str] = []
    for a in raw:
        try:
            addr = parse_address(a)
        except ValueError:
            bad.append(one_line(a, 80))
            continue
        if addr not in emails:
            emails.append(addr)
    if bad:
        raise ValueError(f"invalid attendee address: {', '.join(bad)}")
    return emails


def _validate_event_id(raw: Any) -> str:
    eid = str(raw or "")
    if not _EVENT_ID.match(eid):
        raise ValueError("event_id is not a valid calendar event id")
    return eid


def _organizer(e: dict[str, Any]) -> str:
    org = e.get("organizer")
    return (loose_address(org.get("email")) if isinstance(org, dict) else "") or "calendar"


def _link(value: Any) -> str | None:
    link = one_line(value, LINK_LIMIT)
    return link if link.startswith("https://") else None


def _event_time(part: dict[str, Any] | None, tz: ZoneInfo) -> tuple[str, bool]:
    if not part:
        return "", False
    if "date" in part:
        return one_line(part["date"], 32), True
    dt = part.get("dateTime", "")
    try:
        return datetime.fromisoformat(str(dt).replace("Z", "+00:00")).astimezone(
            tz
        ).isoformat(), False
    except ValueError:
        return one_line(dt, 64), False


# ---- the API ------------------------------------------------------------------------------


@dataclass
class CalendarAPI:
    conn: GoogleConnector

    async def owner_tz(self, user_id: str) -> ZoneInfo:
        """The primary calendar's time zone; UTC when it cannot be read. Looked up per call."""
        try:
            info = await self.conn.request(user_id, "GET", TZ_URL)
            return ZoneInfo(str(info.get("timeZone") or "UTC"))
        except (GoogleAPIError, ZoneInfoNotFoundError, ValueError):
            log.info("calendar time zone unavailable; using UTC")
            return ZoneInfo("UTC")

    def shape(self, e: dict[str, Any], tz: ZoneInfo) -> dict[str, Any]:
        """Only requested fields; addresses as clean bare lines (capped), other people's words
        (title, location, description) fenced as EXTERNAL CONTENT."""
        organizer = _organizer(e)
        start, all_day = _event_time(e.get("start"), tz)
        end, _ = _event_time(e.get("end"), tz)
        listed = [a for a in e.get("attendees") or [] if isinstance(a, dict) and a.get("email")]
        emails = [b for a in listed if (b := loose_address(a.get("email")))]
        out: dict[str, Any] = {
            "id": one_line(e.get("id"), 1024),
            "summary": wrap_external(str(e.get("summary") or "(no title)"), source=organizer),
            "start": start,
            "end": end,
            "all_day": all_day,
            "attendees": {"count": len(listed), "emails": emails[:MAX_LISTED_ATTENDEES]},
            "hangout_link": _link(e.get("hangoutLink")),
            "organizer": organizer,
        }
        if e.get("location"):
            out["location"] = wrap_external(str(e["location"]), source=organizer)
        if e.get("description"):
            out["description"] = wrap_external(
                str(e["description"]), source=organizer, limit=DESCRIPTION_LIMIT
            )
        return out

    async def list_events(self, a: dict[str, Any]) -> dict[str, Any]:
        uid = require_tool_context().user_id
        tz = await self.owner_tz(uid)
        start, end = parse_window(a, tz)
        params: dict[str, Any] = {
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": MAX_EVENTS,
        }
        if a.get("query"):
            params["q"] = str(a["query"])[:200]
        data = await self.conn.request(uid, "GET", EVENTS_URL, params=params)
        items = list(data.get("items") or [])[:MAX_EVENTS]
        return {"time_zone": tz.key, "events": [self.shape(e, tz) for e in items]}

    async def free_slots(self, a: dict[str, Any]) -> dict[str, Any]:
        uid = require_tool_context().user_id
        tz = await self.owner_tz(uid)
        start, end = parse_window(a, tz)
        duration = int(a.get("duration_min") or 0)
        if duration <= 0 or duration > 24 * 60:
            raise ValueError("duration_min must be between 1 and 1440")
        day_from, day_to = parse_working_hours(a.get("working_hours"))
        data = await self.conn.request(
            uid,
            "POST",
            FREEBUSY_URL,
            json={
                "timeMin": start.astimezone(UTC).isoformat(),
                "timeMax": end.astimezone(UTC).isoformat(),
                "items": [{"id": "primary"}],
            },
        )
        busy_raw = ((data.get("calendars") or {}).get("primary") or {}).get("busy") or []
        busy = sorted(
            (
                datetime.fromisoformat(b["start"].replace("Z", "+00:00")).astimezone(tz),
                datetime.fromisoformat(b["end"].replace("Z", "+00:00")).astimezone(tz),
            )
            for b in busy_raw
        )
        slots = compute_free_slots(start, end, busy, timedelta(minutes=duration), day_from, day_to)
        return {
            "time_zone": tz.key,
            "slots": [{"start": s.isoformat(), "end": e.isoformat()} for s, e in slots],
        }

    def _body(self, a: dict[str, Any], tz: ZoneInfo, *, create: bool) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if create or "summary" in a:
            body["summary"] = str(a.get("summary") or "").strip()[:500]
            if create and not body["summary"]:
                raise ValueError("summary is required")
        if "start" in a or "end" in a or create:
            start, end = parse_window(a, tz)
            body["start"] = {"dateTime": start.isoformat(), "timeZone": tz.key}
            body["end"] = {"dateTime": end.isoformat(), "timeZone": tz.key}
        if "attendees" in a:
            body["attendees"] = [{"email": e} for e in _validate_attendees(a.get("attendees"))]
            if create and not body["attendees"]:
                del body["attendees"]
        for key in ("description", "location"):
            if key in a:
                body[key] = str(a[key] or "")[:5_000]
        return body

    async def create_event(self, a: dict[str, Any]) -> dict[str, Any]:
        uid = require_tool_context().user_id
        tz = await self.owner_tz(uid)
        body = self._body(a, tz, create=True)
        updates = "all" if body.get("attendees") else "none"
        e = await self.conn.request(
            uid, "POST", EVENTS_URL, params={"sendUpdates": updates}, json=body
        )
        return self._written(e, tz)

    async def update_event(self, a: dict[str, Any]) -> dict[str, Any]:
        uid = require_tool_context().user_id
        eid = _validate_event_id(a.get("event_id"))
        changes = {k: v for k, v in a.items() if k != "event_id"}
        if not changes:
            raise ValueError("nothing to update: give at least one field to change")
        tz = await self.owner_tz(uid)
        body = self._body(changes, tz, create=False)
        # "all": an event only the owner is on has nobody to notify, and one with other
        # attendees only gets here after the owner approved a card that says they'll be told.
        e = await self.conn.request(
            uid, "PATCH", f"{EVENTS_URL}/{eid}", params={"sendUpdates": "all"}, json=body
        )
        return self._written(e, tz)

    async def delete_event(self, a: dict[str, Any]) -> dict[str, Any]:
        uid = require_tool_context().user_id
        eid = _validate_event_id(a.get("event_id"))
        await self.conn.request(uid, "DELETE", f"{EVENTS_URL}/{eid}", params={"sendUpdates": "all"})
        return {"deleted": True, "id": eid}

    # ---- look-ups before the decision (Tool.preview) ----------------------------------------

    async def _event(self, a: dict[str, Any]) -> dict[str, Any]:
        uid = require_tool_context().user_id
        eid = _validate_event_id(a.get("event_id"))
        e = await self.conn.request(uid, "GET", f"{EVENTS_URL}/{eid}")
        if not isinstance(e, dict) or not e:
            raise GoogleAPIError("Google returned no details for that event.")
        return e

    async def preview_delete(self, a: dict[str, Any]) -> Preview:
        return Preview(delete_card(await self._event(a)), ActionRisk.IRREVERSIBLE)

    async def preview_update(self, a: dict[str, Any]) -> Preview:
        e = await self._event(a)
        guests = _validate_attendees(a["attendees"]) if "attendees" in a else None
        affects_others = bool(others_on(e)) or guests is not None
        risk = ActionRisk.IRREVERSIBLE if affects_others else None
        return Preview(update_card(e, a, guests), risk)

    def _written(self, e: dict[str, Any], tz: ZoneInfo) -> dict[str, Any]:
        start, _ = _event_time(e.get("start"), tz)
        end, _ = _event_time(e.get("end"), tz)
        return {
            "id": one_line(e.get("id"), 1024),
            # an updated event may carry a title an outside organiser wrote
            "summary": wrap_external(str(e.get("summary") or "(no title)"), source=_organizer(e)),
            "start": start,
            "end": end,
            "attendees": len(e.get("attendees") or []),
            "link": _link(e.get("htmlLink")),
        }


def compute_free_slots(
    start: datetime,
    end: datetime,
    busy: list[tuple[datetime, datetime]],
    duration: timedelta,
    day_from: time,
    day_to: time,
) -> list[tuple[datetime, datetime]]:
    """Gaps between busy blocks, clipped to working hours of each day, at least `duration`."""
    slots: list[tuple[datetime, datetime]] = []
    day = start.date()
    while datetime.combine(day, day_from, tzinfo=start.tzinfo) < end and len(slots) < MAX_SLOTS:
        cursor = max(start, datetime.combine(day, day_from, tzinfo=start.tzinfo))
        day_end = min(end, datetime.combine(day, day_to, tzinfo=start.tzinfo))
        for b_start, b_end in busy:
            if b_end <= cursor or b_start >= day_end:
                continue
            if b_start - cursor >= duration:
                slots.append((cursor, b_start))
            cursor = max(cursor, b_end)
        if day_end - cursor >= duration:
            slots.append((cursor, day_end))
        day += timedelta(days=1)
    return slots[:MAX_SLOTS]


# ---- argument checks (pure; run before policy/approval) -------------------------------------

_ANY_TZ = ZoneInfo("UTC")


def _check_window(a: dict[str, Any]) -> None:
    parse_window(a, _ANY_TZ)


def _check_free_slots(a: dict[str, Any]) -> None:
    parse_window(a, _ANY_TZ)
    duration = int(a.get("duration_min") or 0)
    if duration <= 0 or duration > 24 * 60:
        raise ValueError("duration_min must be between 1 and 1440")
    parse_working_hours(a.get("working_hours"))


def _check_create(a: dict[str, Any]) -> None:
    if not str(a.get("summary") or "").strip():
        raise ValueError("summary is required")
    parse_window(a, _ANY_TZ)
    _validate_attendees(a.get("attendees"))


def _check_update(a: dict[str, Any]) -> None:
    _validate_event_id(a.get("event_id"))
    if len(a) < 2:
        raise ValueError("nothing to update: give at least one field to change")
    if "start" in a or "end" in a:
        parse_window(a, _ANY_TZ)
    _validate_attendees(a.get("attendees"))


def _check_event_id(a: dict[str, Any]) -> None:
    _validate_event_id(a.get("event_id"))


# ---- tools --------------------------------------------------------------------------------


def _summarize_create(a: dict[str, Any]) -> str:
    return create_card(a, _validate_attendees(a.get("attendees")))


def _invite_risk(a: dict[str, Any]) -> ActionRisk:
    return ActionRisk.IRREVERSIBLE if a.get("attendees") else ActionRisk.REVERSIBLE


def _attendee_change_risk(a: dict[str, Any]) -> ActionRisk:
    return ActionRisk.IRREVERSIBLE if "attendees" in a else ActionRisk.REVERSIBLE


def calendar_tools(conn: GoogleConnector) -> list[Tool]:
    api = CalendarAPI(conn)
    return [
        Tool(
            "calendar_list_events",
            "List the owner's Google Calendar events between two ISO 8601 times (owner's time "
            "zone when no offset is given). Optional free-text query. At most 50 events.",
            {
                "type": "object",
                "properties": {"start": _ISO, "end": _ISO, "query": {"type": "string"}},
                "required": ["start", "end"],
            },
            ActionRisk.READ_ONLY,
            api.list_events,
            agent="google",
            check=_check_window,
        ),
        Tool(
            "calendar_free_slots",
            "Find free slots of at least duration_min minutes between start and end, inside "
            "working_hours (HH:MM-HH:MM, default 09:00-18:00), from the owner's calendar.",
            {
                "type": "object",
                "properties": {
                    "start": _ISO,
                    "end": _ISO,
                    "duration_min": {"type": "integer", "minimum": 1},
                    "working_hours": {"type": "string"},
                },
                "required": ["start", "end", "duration_min"],
            },
            ActionRisk.READ_ONLY,
            api.free_slots,
            agent="google",
            check=_check_free_slots,
        ),
        Tool(
            "calendar_create_event",
            "Create an event on the owner's primary calendar. With attendees it sends invitations, "
            "so the owner must confirm.",
            {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "start": _ISO,
                    "end": _ISO,
                    "attendees": _ATTENDEES,
                    "description": {"type": "string"},
                    "location": {"type": "string"},
                },
                "required": ["summary", "start", "end"],
            },
            ActionRisk.REVERSIBLE,
            api.create_event,
            agent="google",
            summarize=_summarize_create,
            risk_for=_invite_risk,
            check=_check_create,
        ),
        Tool(
            "calendar_update_event",
            "Change an existing event (only the given fields). If other people are on the event, "
            "or the attendees change, they are notified, so the owner must confirm.",
            {
                "type": "object",
                "properties": {
                    "event_id": {"type": "string"},
                    "summary": {"type": "string"},
                    "start": _ISO,
                    "end": _ISO,
                    "attendees": _ATTENDEES,
                    "description": {"type": "string"},
                    "location": {"type": "string"},
                },
                "required": ["event_id"],
            },
            ActionRisk.REVERSIBLE,
            api.update_event,
            agent="google",
            risk_for=_attendee_change_risk,
            check=_check_update,
            preview=api.preview_update,
        ),
        Tool(
            "calendar_delete_event",
            "Delete an event from the owner's calendar (attendees are notified). Irreversible: "
            "the owner must confirm.",
            {
                "type": "object",
                "properties": {"event_id": {"type": "string"}},
                "required": ["event_id"],
            },
            ActionRisk.IRREVERSIBLE,
            api.delete_event,
            agent="google",
            check=_check_event_id,
            preview=api.preview_delete,
        ),
    ]


__all__ = ["CalendarAPI", "calendar_tools", "compute_free_slots", "parse_when"]
