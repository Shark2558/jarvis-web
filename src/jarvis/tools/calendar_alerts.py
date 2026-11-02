# src/jarvis/tools/calendar_alerts.py
"""Pop-up alerts on calendar events, and the tag that marks a JARVIS reminder (Layer 5/6,
Task & Productivity; slice 11 D4). Pure functions, no I/O.

A JARVIS reminder is an ordinary event on the owner's primary calendar tagged
`extendedProperties.private.jarvis = "reminder"` — private, so only the owner's copy carries it,
and `Events.list(privateExtendedProperty="jarvis=reminder")` finds exactly these. The phone
notification is the event's pop-up alert, shown by the Google Calendar app.

Google's rules (checked 2 Nov 2026 against
developers.google.com/workspace/calendar/api/v3/reference/events and …/events/insert): at most 5
reminder overrides per event, each 0–40,320 minutes (4 weeks) before the start, method "popup" or
"email"; `reminders.useDefault` false means only the overrides apply.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

REMINDER_KEY = "jarvis"
REMINDER_VALUE = "reminder"
REMINDER_FILTER = f"{REMINDER_KEY}={REMINDER_VALUE}"  # Events.list privateExtendedProperty
# The Reminders permission row matches `reminder_*`: the names a calendar tool borrows when its
# look-up finds it is about to change or delete a reminder (`Preview.also`).
REMINDER_UPDATE, REMINDER_DELETE = "reminder_update", "reminder_delete"
REMINDER_PREFIX = "⏰ "  # in the event title, so the Calendar app shows it is a reminder
MAX_ALERTS = 5
MAX_ALERT_MINUTES = 40_320  # 4 weeks
_UNITS = ((10_080, "week"), (1_440, "day"), (60, "hour"))


def is_reminder(event: Mapping[str, Any]) -> bool:
    """True only for an event JARVIS tagged as a reminder (a ⏰ in a title is not enough)."""
    props = event.get("extendedProperties")
    private = props.get("private") if isinstance(props, Mapping) else None
    return isinstance(private, Mapping) and private.get(REMINDER_KEY) == REMINDER_VALUE


def reminder_text(summary: Any) -> str:
    """A reminder's title without the ⏰ JARVIS puts in front."""
    text = "" if summary is None else str(summary)
    return text.removeprefix(REMINDER_PREFIX).removeprefix(REMINDER_PREFIX.strip()).strip()


def check_minutes(value: Any, *, name: str) -> int:
    """A whole number of minutes in Google's range (not a bool, not text)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be a whole number of minutes from 0 to {MAX_ALERT_MINUTES}")
    if not 0 <= value <= MAX_ALERT_MINUTES:
        raise ValueError(
            f"{name} must be from 0 to {MAX_ALERT_MINUTES} minutes (Google allows up to 4 weeks)"
        )
    return value


def alert_minutes(raw: Any) -> list[int]:
    """`reminders_minutes`: up to 5 pop-up offsets → validated, without repeats, sorted."""
    if not isinstance(raw, list):
        raise ValueError("reminders_minutes must be a list of minutes before the start")
    if len(raw) > MAX_ALERTS:
        raise ValueError(f"reminders_minutes: at most {MAX_ALERTS} alerts per event")
    return sorted({check_minutes(m, name="reminders_minutes") for m in raw})


def popup_reminders(minutes: list[int]) -> dict[str, Any]:
    """The event's `reminders` field: exactly these pop-ups ([] = no alerts at all)."""
    return {
        "useDefault": False,
        "overrides": [{"method": "popup", "minutes": m} for m in minutes],
    }


def minutes_label(minutes: int) -> str:
    """0 → 'at the time', 90 → '90 minutes before', 1440 → '1 day before'."""
    if minutes == 0:
        return "at the time"
    for size, unit in _UNITS:
        if minutes % size == 0:
            n = minutes // size
            return f"{n} {unit}{'' if n == 1 else 's'} before"
    return f"{minutes} minute{'' if minutes == 1 else 's'} before"


def alerts_label(minutes: list[int]) -> str:
    return ", ".join(minutes_label(m) for m in minutes) if minutes else "no alerts"


def _overrides(event: Mapping[str, Any]) -> list[tuple[int, str]] | None:
    """(minutes, method) the event has, or None when the calendar's default applies."""
    rem = event.get("reminders")
    if not isinstance(rem, Mapping) or rem.get("useDefault", True) is not False:
        return None
    out: list[tuple[int, str]] = []
    for o in rem.get("overrides") or []:
        if isinstance(o, Mapping) and isinstance(o.get("minutes"), int):
            out.append((int(o["minutes"]), str(o.get("method") or "popup")))
    return sorted(out)


def event_alerts(event: Mapping[str, Any]) -> str:
    """What alerts the event has now, in words (for cards and lists)."""
    found = _overrides(event)
    if found is None:
        return "calendar default"
    if not found:
        return "no alerts"
    return ", ".join(
        minutes_label(m) + ("" if method == "popup" else f" ({method})") for m, method in found
    )


__all__ = [
    "MAX_ALERTS",
    "MAX_ALERT_MINUTES",
    "REMINDER_FILTER",
    "REMINDER_KEY",
    "REMINDER_PREFIX",
    "REMINDER_VALUE",
    "alert_minutes",
    "alerts_label",
    "check_minutes",
    "event_alerts",
    "is_reminder",
    "minutes_label",
    "popup_reminders",
    "reminder_text",
]
