# src/jarvis/tools/provenance.py
"""Whose words is a tool result? Provenance-based trust (Layer 4, slice 11 D8). Pure, no I/O.

A tool result is TRUSTED only when every item in it was written by the owner, or by JARVIS for
him; then reading it does not taint the round (`jarvis.tools.taint`), so "delete my dentist
appointment" (look it up, then change it) needs no approval card. Anything another person or app
may have written keeps the round tainted, exactly as before.

The owner's own (verified 2 Nov 2026 against
developers.google.com/workspace/calendar/api/v3/reference/events and
developers.google.com/workspace/tasks/reference/rest/v1/tasks):

- Calendar event, read from the owner's PRIMARY calendar (`self` is relative to the calendar the
  copy was read from — never use this for another calendar): `organizer.self` and `creator.self`
  both true (read-only fields Google sets), nobody else on it (every attendee is `self`;
  `attendeesOmitted` not set), and `eventType` one of the owner's own kinds below. `fromGmail`
  (Gmail put it there from a mail), `birthday` (a contact's name) and any type Google adds later
  are not. A JARVIS reminder counts when it meets the same rule — the tag alone proves nothing.
- To-do: no `links` (Gmail "Add to Tasks", a Chat message, a Keep note — read-only, set by
  Google) and no `assignmentInfo` (assigned from a Doc or a Chat space).
- A result is the owner's own only when every item is; an empty result is (nobody's words).

What this cannot see (accepted, plan D8): an app the owner authorised to write to his calendar or
to-dos as him, a person he lets edit his primary calendar changing an event he created, an .ics
he imports, and text JARVIS wrote for him after he approved a card. Item text stays fenced as
external content whatever the verdict: fencing and trust are independent.

A tool vouches by returning `vouch(result, verdict)`; the gateway unwraps it and honours it only
from a tool declared `may_vouch` (`jarvis.tools.base.Tool`), and only for a result that ran.
`is_owner_authored_event` / `is_owner_authored_task` are the hook for other features (the
Recently-deleted bin keeps the flag its item had).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

# Calendar API `eventType` values only the owner makes on his own calendar. A missing type is
# "default" (Google: "A regular event or not further specified").
OWN_EVENT_TYPES = frozenset({"default", "focusTime", "outOfOffice", "workingLocation"})


def _is_self(part: Any) -> bool:
    return isinstance(part, Mapping) and part.get("self") is True


def is_owner_authored_event(event: Any) -> bool:
    """True only for an event (from the owner's primary calendar) nobody but the owner — or
    JARVIS for him — can have written. Fails closed on anything malformed."""
    if not isinstance(event, Mapping):
        return False
    if not (_is_self(event.get("organizer")) and _is_self(event.get("creator"))):
        return False
    if event.get("eventType", "default") not in OWN_EVENT_TYPES:
        return False
    if event.get("attendeesOmitted"):
        return False
    attendees = event.get("attendees") or []
    return isinstance(attendees, list) and all(_is_self(a) for a in attendees)


def is_owner_authored_task(task: Any) -> bool:
    """True only for a to-do no other app or person put on the list."""
    return isinstance(task, Mapping) and not task.get("links") and not task.get("assignmentInfo")


def all_owner_authored(items: Iterable[Any], rule: Callable[[Any], bool]) -> bool:
    """Every item passes `rule` (an empty result does)."""
    return all(rule(item) for item in items)


@dataclass(frozen=True)
class OwnerItems:
    """A tool's result that the tool found to be entirely the owner's own. Only the gateway
    unwraps it; nothing else ever sees the wrapper."""

    value: Any


def vouch(value: Any, owner_authored: bool) -> Any:
    """What a tool returns: `value` itself, marked as the owner's own when `owner_authored`."""
    return OwnerItems(value) if owner_authored else value


def unwrap(out: Any) -> tuple[Any, bool]:
    """(the plain result, whether the tool vouched for it)."""
    if isinstance(out, OwnerItems):
        return out.value, True
    return out, False


__all__ = [
    "OWN_EVENT_TYPES",
    "OwnerItems",
    "all_owner_authored",
    "is_owner_authored_event",
    "is_owner_authored_task",
    "unwrap",
    "vouch",
]
