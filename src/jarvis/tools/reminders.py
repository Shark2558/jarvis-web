# src/jarvis/tools/reminders.py
"""Reminders (Layer 5/6, Task & Productivity; slice 11 D4): tagged events on the owner's primary
Google Calendar. The reminder IS the event's pop-up alert, which the Google Calendar app shows on
the owner's phone.

A reminder is 5 minutes long, `transparent` (Google: it "does not block time on the calendar", so
free-time search and the brief's free blocks ignore it), never has attendees, and carries
`extendedProperties.private.jarvis = "reminder"` (`jarvis.tools.calendar_alerts`). Tools:
reminder_add (R2), reminders_list (R1), reminder_update (R2; tagged events only, refused in plain
words otherwise). Deleting one is `calendar_delete_event` with its id — undo-able (slice 11 D2) —
and every description says so. No new Google scope: calendar.events covers extended properties.

Times are ISO 8601; a naive time is the owner's calendar time zone. An alert that would already
have popped up (beyond a 2-minute grace) is refused. A repeat (daily / weekdays / weekly /
monthly) becomes an RFC 5545 RRULE that always ends: on `repeat_until`, at most a year after the
first reminder (or after today, for an older one). The pure argument checks run before the
policy decision and are lenient about the zone (a naive time read in the latest zone, UTC−12);
the exact checks run with the owner's zone.

Slice 11 D8: all three vouch for their result (`may_vouch`) when every reminder in it is the
owner's own by the calendar rule (`provenance.is_owner_authored_event`: the tag alone proves
nothing), and reminders_list takes a `query` (Google's `q`) to look one up by its words.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jarvis.core.guardrails import ActionRisk
from jarvis.integrations.google import GoogleConnector
from jarvis.tools.base import Preview, Tool
from jarvis.tools.calendar_alerts import (
    MAX_ALERT_MINUTES,
    REMINDER_FILTER,
    REMINDER_KEY,
    REMINDER_PREFIX,
    REMINDER_VALUE,
    check_minutes,
    event_alerts,
    is_reminder,
    minutes_label,
    popup_reminders,
    reminder_text,
)
from jarvis.tools.calendar_cards import others_on
from jarvis.tools.card import one_line, quoted
from jarvis.tools.context import require_tool_context
from jarvis.tools.external import wrap_external
from jarvis.tools.google_calendar import (
    EVENTS_URL,
    QUERY,
    CalendarAPI,
    _event_time,
    _validate_event_id,
    parse_when,
    query_arg,
)
from jarvis.tools.provenance import (
    all_owner_authored,
    is_owner_authored_event,
    mark_outside,
    vouch,
)

SOURCE = "reminders"
TEXT_MAX = 200
LENGTH = timedelta(minutes=5)
PAST_GRACE = timedelta(minutes=2)
MAX_AHEAD = timedelta(days=5 * 366)
MAX_REPEAT = timedelta(days=365)
DEFAULT_WINDOW = timedelta(days=7)
MAX_WINDOW = timedelta(days=366)
MAX_LISTED = 50
REPEATS = ("none", "daily", "weekdays", "weekly", "monthly")
_FREQ = {  # weekdays before weekly: `_repeat_of` matches prefixes in this order
    "daily": "FREQ=DAILY",
    "weekdays": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR",
    "weekly": "FREQ=WEEKLY",
    "monthly": "FREQ=MONTHLY",
}
_LATEST = ZoneInfo("Etc/GMT+12")  # UTC−12 (POSIX sign): the latest a naive time can mean
_CHANGES = ("text", "when", "minutes_before", "repeat")
DELETE_NOTE = (
    "A pop-up from the Google Calendar app on the owner's phone. To delete it use "
    "calendar_delete_event with this id (the owner can undo a delete)."
)
HOW_TO = (
    "Change one with reminder_update (event_id = id). Delete one with calendar_delete_event "
    "(event_id = id; the owner can undo it). For every occurrence of a repeating reminder use its "
    "series_id instead of id."
)
NOT_A_REMINDER = (
    "That event is not a reminder JARVIS set, so reminder_update won't change it; use "
    "calendar_update_event for an ordinary event."
)
SHARED = (
    "That reminder now has other people on it, so JARVIS won't change it as a reminder; use "
    "calendar_update_event (the owner will be asked first)."
)
ONE_OCCURRENCE = (
    "That id is one occurrence of a repeating reminder: to change how it repeats, use its "
    "series_id (from reminders_list) as event_id."
)


def utcnow() -> datetime:
    return datetime.now(UTC)


# ---- argument rules (pure) --------------------------------------------------------------------


def _text_arg(value: Any) -> str:
    text = one_line(value, TEXT_MAX + 1) if isinstance(value, str) else ""
    if not text:
        raise ValueError("text is required (what to remind the owner of, in a few words)")
    if len(text) > TEXT_MAX:
        raise ValueError(f"text is too long (at most {TEXT_MAX} characters)")
    return text


def _repeat_arg(value: Any) -> str:
    repeat = value or "none"
    if repeat not in REPEATS:
        raise ValueError(f"repeat must be one of: {', '.join(REPEATS)}")
    return str(repeat)


def _until_arg(a: dict[str, Any]) -> date | None:
    raw = a.get("repeat_until")
    if raw is None:
        return None
    try:
        return date.fromisoformat(str(raw).strip())
    except ValueError:
        raise ValueError("repeat_until must be a date, YYYY-MM-DD") from None


def _fmt(dt: datetime) -> str:
    """'Fri 15 Jan 17:00' (no zero-padded day, portable)."""
    return f"{dt:%a} {dt.day} {dt:%b %H:%M}"


def _passed(alert: datetime) -> str:
    return (
        f"that time has already passed (the alert would pop up at {_fmt(alert)}); give a time in "
        "the future"
    )


def _check_future(at: datetime, minutes_before: int, now: datetime) -> None:
    alert = at - timedelta(minutes=minutes_before)
    if alert < now - PAST_GRACE:
        raise ValueError(_passed(alert))
    if at - now > MAX_AHEAD:
        raise ValueError("when is too far ahead (at most 5 years)")


def _repeat_rule(
    repeat: str, first: datetime, until: date | None, today: date, *, slack: int = 0
) -> tuple[str | None, date | None]:
    """→ (the RRULE line, its last day), or (None, None) for no repeat. `slack` days widen the
    bounds for the zone-blind pre-check."""
    if repeat == "none":
        if until is not None:
            raise ValueError("repeat_until goes with repeat: give both")
        return None, None
    day = first.date()
    cap = max(day, today) + MAX_REPEAT
    last = until if until is not None else cap
    if last < day - timedelta(days=slack):
        raise ValueError("repeat_until is before the first reminder")
    if last > cap + timedelta(days=slack):
        raise ValueError(
            f"repeat_until can be at most a year ahead ({cap.isoformat()}); the owner can extend "
            "it later"
        )
    end = datetime.combine(min(last, cap), time(23, 59, 59), tzinfo=first.tzinfo)
    return f"RRULE:{_FREQ[repeat]};UNTIL={end.astimezone(UTC):%Y%m%dT%H%M%SZ}", min(last, cap)


def _span(start: datetime, end: datetime) -> None:
    if end <= start:
        raise ValueError("end must be after start (start must come before end)")
    if end - start > MAX_WINDOW:
        raise ValueError(f"the window can be at most {MAX_WINDOW.days} days")


# ---- card text (pure) -------------------------------------------------------------------------


def _card_time(value: Any) -> str:
    """A time the model passed, as a person reads it; its offset shown when it has one."""
    try:
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return one_line(value, 40)
    return _fmt(dt) if dt.tzinfo is None else f"{_fmt(dt)} (UTC{dt.isoformat()[-6:]})"


def _start_part(e: dict[str, Any]) -> dict[str, Any]:
    part = e.get("start")
    return part if isinstance(part, dict) else {}


def _event_when(e: dict[str, Any]) -> str:
    part = _start_part(e)
    try:
        dt = datetime.fromisoformat(str(part.get("dateTime")).replace("Z", "+00:00"))
        return _fmt(dt.astimezone(ZoneInfo(str(part.get("timeZone")))))
    except (ValueError, ZoneInfoNotFoundError):
        return _card_time(part.get("dateTime") or part.get("date") or "?")


def _repeat_of(e: dict[str, Any]) -> str:
    if e.get("recurringEventId"):
        return "repeating (this occurrence)"
    rules = [str(r) for r in e.get("recurrence") or [] if str(r).startswith("RRULE:")]
    if not rules:
        return "no"
    return next((name for name, f in _FREQ.items() if rules[0].startswith(f"RRULE:{f}")), "yes")


def _repeat_words(repeat: str, until: Any) -> str:
    if repeat == "none":
        return "no"
    return repeat + (f" until {one_line(until, 20)}" if until else "")


def add_card(a: dict[str, Any]) -> str:
    """'Remind you: call Ravi · Mon 3 Nov 17:00' (+ alert offset, + repeat)."""
    parts = [f"Remind you: {one_line(a.get('text'), TEXT_MAX)}", _card_time(a.get("when"))]
    if a.get("minutes_before"):
        parts.append(minutes_label(int(a["minutes_before"])))
    repeat = _repeat_arg(a.get("repeat"))
    if repeat != "none":
        parts.append(f"repeats {_repeat_words(repeat, a.get('repeat_until'))}")
    return " · ".join(parts)


def update_card(e: dict[str, Any], a: dict[str, Any]) -> str:
    title = quoted(reminder_text(e.get("summary")) or "(no text)", 120)
    lines = [f"Change reminder {title} ({_event_when(e)})"]
    if "text" in a:
        lines.append(f"• text: {title} → {quoted(a['text'], 120)}")
    if "when" in a:
        lines.append(f"• time: {_event_when(e)} → {_card_time(a['when'])}")
    if "minutes_before" in a:
        lines.append(f"• alert: {event_alerts(e)} → {minutes_label(int(a['minutes_before']))}")
    if "repeat" in a:
        new = _repeat_words(_repeat_arg(a["repeat"]), a.get("repeat_until"))
        lines.append(f"• repeat: {_repeat_of(e)} → {new}")
    lines.append("Only your calendar changes.")
    return "\n".join(lines)


def _own_reminder(e: dict[str, Any], a: dict[str, Any]) -> None:
    if not is_reminder(e):
        raise ValueError(NOT_A_REMINDER)
    if others_on(e):
        raise ValueError(SHARED)
    if "repeat" in a and e.get("recurringEventId"):
        raise ValueError(ONE_OCCURRENCE)


# ---- the API ----------------------------------------------------------------------------------


@dataclass
class ReminderAPI:
    cal: CalendarAPI
    clock: Callable[[], datetime] = utcnow

    # ---- pure checks (before the policy decision; zone-blind, so lenient) --------------------

    def _lenient(self, value: Any, minutes_before: int) -> datetime:
        at = parse_when(value, _LATEST, name="when")
        _check_future(at, minutes_before, self.clock())
        return at

    def check_add(self, a: dict[str, Any]) -> None:
        _text_arg(a.get("text"))
        minutes = check_minutes(a.get("minutes_before", 0), name="minutes_before")
        at = self._lenient(a.get("when"), minutes)
        until = _until_arg(a)
        _repeat_rule(_repeat_arg(a.get("repeat")), at, until, self.clock().date(), slack=1)

    def check_list(self, a: dict[str, Any]) -> None:
        start = parse_when(a["start"], _LATEST, name="start") if a.get("start") else None
        end = parse_when(a["end"], _LATEST, name="end") if a.get("end") else None
        if start is not None and end is not None:
            _span(start, end)
        query_arg(a.get("query"))

    def check_update(self, a: dict[str, Any]) -> None:
        _validate_event_id(a.get("event_id"))
        if not set(_CHANGES) & a.keys():
            raise ValueError("nothing to change: give new text, when, minutes_before or repeat")
        if "text" in a:
            _text_arg(a["text"])
        minutes = check_minutes(a.get("minutes_before", 0), name="minutes_before")
        if "when" in a:
            self._lenient(a["when"], minutes)
        if "repeat" not in a and "repeat_until" in a:
            raise ValueError("repeat_until goes with repeat: give both")
        if "repeat" in a:
            _repeat_arg(a["repeat"])
            _until_arg(a)

    # ---- tools -------------------------------------------------------------------------------

    async def _zone(self) -> tuple[str, ZoneInfo]:
        uid = require_tool_context().user_id
        return uid, await self.cal.owner_tz(uid)

    async def add(self, a: dict[str, Any]) -> Any:
        uid, tz = await self._zone()
        now = self.clock()
        text = _text_arg(a.get("text"))
        minutes = check_minutes(a.get("minutes_before", 0), name="minutes_before")
        at = parse_when(a.get("when"), tz, name="when")
        _check_future(at, minutes, now)
        repeat = _repeat_arg(a.get("repeat"))
        rule, last = _repeat_rule(repeat, at, _until_arg(a), now.astimezone(tz).date())
        body: dict[str, Any] = {
            "summary": REMINDER_PREFIX + text,
            **_slot(at, tz),
            "transparency": "transparent",
            "reminders": popup_reminders([minutes]),
            "extendedProperties": {"private": {REMINDER_KEY: REMINDER_VALUE}},
        }
        if rule is not None:
            body["recurrence"] = [rule]
        if require_tool_context().outside:  # D8: other people's words: never the owner's own
            body = mark_outside(body)
        e = await self.cal.conn.request(
            uid, "POST", EVENTS_URL, params={"sendUpdates": "none"}, json=body
        )
        out = {
            "status": "set",
            "id": one_line(e.get("id"), 1024),
            "text": text,
            "at": at.isoformat(),
            "alert": minutes_label(minutes),
            "repeats": f"{repeat} until {last.isoformat()}" if last is not None else None,
            "time_zone": tz.key,
            "note": DELETE_NOTE,
        }
        return vouch(out, is_owner_authored_event(e))

    async def list_reminders(self, a: dict[str, Any]) -> Any:
        uid, tz = await self._zone()
        now = self.clock().astimezone(tz)
        start = parse_when(a["start"], tz, name="start") if a.get("start") else now
        end = parse_when(a["end"], tz, name="end") if a.get("end") else start + DEFAULT_WINDOW
        _span(start, end)
        params: dict[str, Any] = {
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": MAX_LISTED,
            "privateExtendedProperty": REMINDER_FILTER,
        }
        if q := query_arg(a.get("query")):
            params["q"] = q
        data = await self.cal.conn.request(uid, "GET", EVENTS_URL, params=params)
        items = [e for e in list(data.get("items") or [])[:MAX_LISTED] if isinstance(e, dict)]
        shown = [e for e in items if is_reminder(e)]
        out = {
            "time_zone": tz.key,
            "from": start.isoformat(),
            "to": end.isoformat(),
            "reminders": [_shape(e, tz) for e in shown],
            "how_to": HOW_TO,
        }
        return vouch(out, all_owner_authored(shown, is_owner_authored_event))

    async def update(self, a: dict[str, Any]) -> Any:
        uid, tz = await self._zone()
        e = await self.cal._event(a)  # the authoritative look-up: the tag is checked here too
        _own_reminder(e, a)
        body = self._changes(a, e, tz)
        if require_tool_context().outside:  # D8: keep its tag and properties, add the mark
            body = mark_outside(body, e)
        eid = _validate_event_id(a.get("event_id"))
        out = await self.cal.conn.request(
            uid, "PATCH", f"{EVENTS_URL}/{eid}", params={"sendUpdates": "none"}, json=body
        )
        return vouch({"status": "updated", **_shape(out, tz)}, is_owner_authored_event(out))

    def _changes(self, a: dict[str, Any], e: dict[str, Any], tz: ZoneInfo) -> dict[str, Any]:
        body: dict[str, Any] = {}
        now = self.clock()
        if "text" in a:
            body["summary"] = REMINDER_PREFIX + _text_arg(a["text"])
        minutes = check_minutes(a.get("minutes_before", _popup_of(e)), name="minutes_before")
        start = parse_when(a["when"], tz, name="when") if "when" in a else None
        if start is not None:  # its alert (new or kept) must still be ahead
            _check_future(start, minutes, now)
            body.update(_slot(start, tz))
        if "minutes_before" in a:
            body["reminders"] = popup_reminders([minutes])
        if "repeat" in a:
            first = start or _start_of(e, tz)
            today = now.astimezone(tz).date()
            rule, _ = _repeat_rule(_repeat_arg(a["repeat"]), first, _until_arg(a), today)
            body["recurrence"] = [rule] if rule is not None else []
        return body

    async def preview_update(self, a: dict[str, Any]) -> Preview:
        e = await self.cal._event(a)
        _own_reminder(e, a)
        return Preview(update_card(e, a))


def _slot(at: datetime, tz: ZoneInfo) -> dict[str, Any]:
    return {
        "start": {"dateTime": at.isoformat(), "timeZone": tz.key},
        "end": {"dateTime": (at + LENGTH).isoformat(), "timeZone": tz.key},
    }


def _popup_of(e: dict[str, Any]) -> int:
    """The reminder's pop-up offset now (0 when it has none of its own)."""
    rem = e.get("reminders")
    for o in (rem.get("overrides") or []) if isinstance(rem, dict) else []:
        if isinstance(o, dict) and o.get("method") == "popup" and isinstance(o.get("minutes"), int):
            return int(o["minutes"])
    return 0


def _start_of(e: dict[str, Any], tz: ZoneInfo) -> datetime:
    part = _start_part(e)
    try:
        return datetime.fromisoformat(str(part.get("dateTime")).replace("Z", "+00:00")).astimezone(
            tz
        )
    except ValueError:
        raise ValueError("that reminder has no time of day; give a new `when`") from None


def _shape(e: dict[str, Any], tz: ZoneInfo) -> dict[str, Any]:
    """A reminder for the model: its text fenced (it may have been edited in the Calendar app,
    or copied from someone else's words), when it pops up, and the ids to change it by."""
    start, _ = _event_time(e.get("start"), tz)
    series = one_line(e.get("recurringEventId"), 1024)
    out: dict[str, Any] = {
        "id": one_line(e.get("id"), 1024),
        "text": wrap_external(
            reminder_text(e.get("summary")) or "(no text)", source=SOURCE, limit=TEXT_MAX
        ),
        "at": start,
        "alert": event_alerts(e),
        "repeating": bool(series or e.get("recurrence")),
    }
    if series:
        out["series_id"] = series
    return out


# ---- tools ------------------------------------------------------------------------------------

_WHEN = {
    "type": "string",
    "description": "ISO 8601 date-time; no offset = the owner's time zone (2027-01-15T17:00:00)",
}
_TEXT = {"type": "string", "maxLength": TEXT_MAX, "description": "What to remind the owner of"}
_MINUTES = {
    "type": "integer",
    "minimum": 0,
    "maximum": MAX_ALERT_MINUTES,
    "description": "Pop up this many minutes before `when` (default 0: at that time)",
}
_REPEAT = {"type": "string", "enum": list(REPEATS), "description": "Default none"}
_UNTIL = {
    "type": "string",
    "description": "Last day of a repeat, YYYY-MM-DD (default and maximum: a year after the first)",
}
_DELETE = " To delete a reminder use calendar_delete_event with its id (the owner can undo it)."


def reminder_tools(conn: GoogleConnector, *, clock: Callable[[], datetime] = utcnow) -> list[Tool]:
    api = ReminderAPI(CalendarAPI(conn), clock)
    return [
        Tool(
            "reminder_add",
            "Set a reminder for 'remind me to …': a pop-up on the owner's phone from the Google "
            "Calendar app at `when`, or minutes_before earlier, optionally repeating (ends on "
            "repeat_until, at most a year ahead). For 'remind me before <event>' use "
            "reminders_minutes on calendar_update_event instead." + _DELETE,
            {
                "type": "object",
                "properties": {
                    "text": _TEXT,
                    "when": _WHEN,
                    "minutes_before": _MINUTES,
                    "repeat": _REPEAT,
                    "repeat_until": _UNTIL,
                },
                "required": ["text", "when"],
            },
            ActionRisk.REVERSIBLE,
            api.add,
            agent="google",
            summarize=add_card,
            check=api.check_add,
            may_vouch=True,
        ),
        Tool(
            "reminders_list",
            "List the owner's reminders (set with reminder_add) between start and end (default: "
            "the next 7 days), with the ids reminder_update takes. Optional query." + _DELETE,
            {"type": "object", "properties": {"start": _WHEN, "end": _WHEN, "query": QUERY}},
            ActionRisk.READ_ONLY,
            api.list_reminders,
            agent="google",
            check=api.check_list,
            may_vouch=True,
        ),
        Tool(
            "reminder_update",
            "Change a reminder set with reminder_add (only the given fields): text, when, "
            "minutes_before or repeat. Ordinary events are refused: use calendar_update_event."
            + _DELETE,
            {
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "id or series_id from the list"},
                    "text": _TEXT,
                    "when": _WHEN,
                    "minutes_before": _MINUTES,
                    "repeat": _REPEAT,
                    "repeat_until": _UNTIL,
                },
                "required": ["event_id"],
            },
            ActionRisk.REVERSIBLE,
            api.update,
            agent="google",
            check=api.check_update,
            preview=api.preview_update,
            may_vouch=True,
        ),
    ]


__all__ = ["REPEATS", "ReminderAPI", "add_card", "reminder_tools", "update_card"]
