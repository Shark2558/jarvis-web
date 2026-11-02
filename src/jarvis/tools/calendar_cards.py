# src/jarvis/tools/calendar_cards.py
"""Approval-card text for the calendar write tools (Layer 4 → 1). Pure functions, no I/O.

A card must let the owner see exactly what will change and who will hear about it: the event's
real title and time (looked up first by the tool's preview), every changed field as
old → new, and the other people Google will email. Every value goes through
`jarvis.tools.card.one_line`, because titles and descriptions are often written by someone else.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from jarvis.tools.addresses import display_address
from jarvis.tools.calendar_alerts import alert_minutes, alerts_label, event_alerts
from jarvis.tools.card import one_line, quoted

TITLE_LIMIT = 120
TIME_LIMIT = 40
FIELD_LIMIT = 200
CHANGE_LIMIT = 80
MAX_PEOPLE_SHOWN = 10


def others_on(event: dict[str, Any]) -> list[str]:
    """Everyone on the event except the owner (the attendee Google flags `self`)."""
    out: list[str] = []
    for a in event.get("attendees") or []:
        if not isinstance(a, dict) or a.get("self"):
            continue
        who = one_line(a.get("email") or a.get("displayName") or "a guest", 254).lower()
        if who not in out:
            out.append(who)
    return out


def _people(addrs: list[str]) -> str:
    if not addrs:
        return "(none)"
    shown = ", ".join(display_address(a) for a in addrs[:MAX_PEOPLE_SHOWN])
    more = len(addrs) - MAX_PEOPLE_SHOWN
    return shown + (f" and {more} more" if more > 0 else "")


def _value(value: Any, limit: int) -> str:
    return quoted(value, limit) if one_line(value, limit) else "(none)"


def _time_of(part: Any) -> str:
    if not isinstance(part, dict):
        return "?"
    return one_line(part.get("dateTime") or part.get("date") or "?", TIME_LIMIT)


def when_arg(value: Any) -> str:
    """A time the model passed: shown as given, flagged when it has no offset."""
    text = one_line(value, TIME_LIMIT)
    try:
        naive = datetime.fromisoformat(text.replace("Z", "+00:00")).tzinfo is None
    except ValueError:
        return text
    return f"{text} (calendar time zone)" if naive else text


def _title(event: dict[str, Any]) -> str:
    return quoted(event.get("summary") or "(no title)", TITLE_LIMIT)


def _when(event: dict[str, Any]) -> str:
    return f"{_time_of(event.get('start'))} → {_time_of(event.get('end'))}"


def _notify(people: list[str], what: str) -> str:
    if not people:
        return "Nobody else is on this event: only your calendar changes."
    n = len(people)
    return (
        f"Google will email {n} other {'person' if n == 1 else 'people'} {what}: {_people(people)}"
    )


def create_card(a: dict[str, Any], guests: list[str]) -> str:
    lines = [
        f"Create event {quoted(a.get('summary'), TITLE_LIMIT)}",
        f"When: {when_arg(a.get('start'))} → {when_arg(a.get('end'))}",
        f"Invites (Google emails each of them): {_people(guests)}"
        if guests
        else "No invitations: only your calendar changes.",
    ]
    if one_line(a.get("location"), FIELD_LIMIT):
        lines.append(f"Location: {one_line(a.get('location'), FIELD_LIMIT)}")
    if one_line(a.get("description"), FIELD_LIMIT):
        lines.append(f"Description: {one_line(a.get('description'), FIELD_LIMIT)}")
    if "reminders_minutes" in a:
        lines.append(f"Alerts: {alerts_label(alert_minutes(a['reminders_minutes']))}")
    return "\n".join(lines)


def delete_card(event: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"Delete event {_title(event)}",
            f"When: {_when(event)}",
            _notify(others_on(event), "that it is cancelled"),
        ]
    )


def _changes(event: dict[str, Any], a: dict[str, Any], new_guests: list[str] | None) -> list[str]:
    out: list[str] = []
    if "summary" in a:
        old, new = _value(event.get("summary"), CHANGE_LIMIT), _value(a["summary"], CHANGE_LIMIT)
        out.append(f"• title: {old} → {new}")
    for key in ("start", "end"):
        if key in a:
            out.append(f"• {key}: {_time_of(event.get(key))} → {when_arg(a[key])}")
    for key in ("location", "description"):
        if key in a:
            old, new = _value(event.get(key), CHANGE_LIMIT), _value(a[key], CHANGE_LIMIT)
            out.append(f"• {key}: {old} → {new}")
    if new_guests is not None:
        out.append(f"• attendees: {_people(others_on(event))} → {_people(new_guests)}")
    if "reminders_minutes" in a:
        new = alerts_label(alert_minutes(a["reminders_minutes"]))
        out.append(f"• alerts: {event_alerts(event)} → {new}")
    return out


def update_card(event: dict[str, Any], a: dict[str, Any], new_guests: list[str] | None) -> str:
    """`new_guests` is the validated `attendees` argument, or None when it is not changing."""
    told = sorted(set(others_on(event)) | set(new_guests or []))
    return "\n".join(
        [
            f"Update event {_title(event)} ({_when(event)})",
            "Changes:",
            *_changes(event, a, new_guests),
            _notify(told, "about the change"),
        ]
    )


__all__ = ["create_card", "delete_card", "others_on", "update_card", "when_arg"]
