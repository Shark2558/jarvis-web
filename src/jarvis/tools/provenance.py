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
- Neither, when JARVIS wrote it from OUTSIDE content (security review of A+B): a write made in a
  round that had read other people's text — or approved on a card proposed in such a round —
  marks what it writes. An event or reminder carries `extendedProperties.private.jarvis_src =
  "outside"` (`mark_outside`; JARVIS never removes it); a to-do's id goes into the owner's set of
  outside to-dos (`jarvis.tools.task_marks`; unreadable set ⇒ every to-do counts as outside). A
  restore from Recently deleted of an item that was not the owner's own is marked the same way.
- A result is the owner's own only when every item is; an empty result is (nobody's words).

What this cannot see (accepted, plan D8): an app the owner authorised to write to his calendar or
to-dos as him, a person he lets edit his primary calendar changing an event he created, and an
.ics he imports. Item text stays fenced as external content whatever the verdict: fencing and
trust are independent.

A tool vouches by returning `vouch(result, verdict)`; the gateway unwraps it and honours it only
from a tool declared `may_vouch` (`jarvis.tools.base.Tool`), and only for a result that ran.
`is_owner_authored_event` / `is_owner_authored_task` are the ONE rule: Recently deleted records
their verdict on each kept item (`jarvis.undo`) and its listing reuses `all_owner_authored`.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

# Calendar API `eventType` values only the owner makes on his own calendar. A missing type is
# "default" (Google: "A regular event or not further specified").
OWN_EVENT_TYPES = frozenset({"default", "focusTime", "outOfOffice", "workingLocation"})
# What a write made from outside content leaves on an event (`extendedProperties.private`).
OUTSIDE_KEY = "jarvis_src"
OUTSIDE_VALUE = "outside"


def _is_self(part: Any) -> bool:
    return isinstance(part, Mapping) and part.get("self") is True


def _private(event: Mapping[str, Any]) -> Mapping[str, Any]:
    props = event.get("extendedProperties")
    private = props.get("private") if isinstance(props, Mapping) else None
    return private if isinstance(private, Mapping) else {}


def is_marked_outside(event: Any) -> bool:
    """JARVIS wrote this event from other people's words (`mark_outside`)."""
    return isinstance(event, Mapping) and _private(event).get(OUTSIDE_KEY) == OUTSIDE_VALUE


def mark_outside(
    body: Mapping[str, Any], current: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """A new event body (insert or patch) that also carries the outside mark. `current`: the
    event as Google has it now, so a patch keeps every extended property it already has."""
    base = current if current is not None else {}
    old = base.get("extendedProperties") if isinstance(base, Mapping) else None
    sent = body.get("extendedProperties")
    props: dict[str, Any] = {
        **(copy.deepcopy(dict(old)) if isinstance(old, Mapping) else {}),
        **(copy.deepcopy(dict(sent)) if isinstance(sent, Mapping) else {}),
    }
    private = {**_private(base), **_private(body), OUTSIDE_KEY: OUTSIDE_VALUE}
    return {**body, "extendedProperties": {**props, "private": private}}


def is_owner_authored_event(event: Any) -> bool:
    """True only for an event (from the owner's primary calendar) nobody but the owner — or
    JARVIS for him, from his words — can have written. Fails closed on anything malformed."""
    if not isinstance(event, Mapping):
        return False
    if not (_is_self(event.get("organizer")) and _is_self(event.get("creator"))):
        return False
    if event.get("eventType", "default") not in OWN_EVENT_TYPES:
        return False
    if event.get("attendeesOmitted") or is_marked_outside(event):
        return False
    attendees = event.get("attendees") or []
    return isinstance(attendees, list) and all(_is_self(a) for a in attendees)


def is_owner_authored_task(task: Any, *, outside: Collection[str] | None = frozenset()) -> bool:
    """True only for a to-do no other app or person put on the list, and that JARVIS did not
    write from outside content. `outside`: the owner's outside to-do ids; None = that set could
    not be read, so nothing counts (fail closed)."""
    if outside is None or not isinstance(task, Mapping):
        return False
    if task.get("links") or task.get("assignmentInfo"):
        return False
    return task.get("id") not in outside


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
    "OUTSIDE_KEY",
    "OUTSIDE_VALUE",
    "OWN_EVENT_TYPES",
    "OwnerItems",
    "all_owner_authored",
    "is_marked_outside",
    "is_owner_authored_event",
    "is_owner_authored_task",
    "mark_outside",
    "unwrap",
    "vouch",
]
