# src/jarvis/tools/calendar_undo.py
"""Undo-able event deletes (slice 11 D1/D2; Layer 5/6): which deletes can be undone, the copy
kept before one, and how an event comes back.

Risk of a delete (decided on the event as Google has it, by the tool's preview and again when it
runs): R2 — undo-able — for an event only the owner is on, that the owner organises, of the
ordinary kind, and not repeating; a JARVIS reminder (`extendedProperties.private.jarvis ==
"reminder"`, made by the reminder tools) may repeat: its rule comes back with it. Everything else
is R3 (a card and, when the owner requires one, a passkey): Google emails the other people, a
restore can't bring back an organiser's event or a series' changed occurrences, and special event
types (out of office, focus time, …) can't be recreated as they were.

The copy keeps exactly what a restore sends back — summary, description, location, start/end
(with their time zones), reminders, colorId, transparency, visibility, extendedProperties, and
recurrence for a reminder — and never attendees, ids or links. A restore recreates the event (new
id, `sendUpdates=none`), from those fields only, whatever the stored copy holds.

Each kept copy also records whether the owner wrote the event (`owner_authored`: plan D8's one
rule, `provenance.is_owner_authored_event`), so a listing of Recently deleted can be trusted when
every item in it is the owner's own words, and the delete's own result is trusted by the same
flag. A restore of an event that was NOT the owner's own carries the outside mark
(`provenance.mark_outside`), so recreating it (as the owner, with JARVIS as creator) never makes
someone else's words his.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from jarvis.core.guardrails import ActionRisk
from jarvis.integrations.google import GoogleAPIError, GoogleConnector
from jarvis.tools.calendar_alerts import is_reminder
from jarvis.tools.calendar_cards import others_on
from jarvis.tools.card import one_line
from jarvis.tools.context import require_tool_context
from jarvis.tools.provenance import is_owner_authored_event, mark_outside, vouch
from jarvis.undo.service import Restored, UndoBin
from jarvis.undo.tools import deleted_result

_RESTORED = (
    "summary",
    "description",
    "location",
    "start",
    "end",
    "reminders",
    "colorId",
    "transparency",
    "visibility",
    "extendedProperties",
)
ORDINARY_TYPES = frozenset({"default"})
CHANGED = (
    "That event changed since it was checked (it can no longer be undone), so nothing was "
    "deleted. Look it up again and ask the owner."
)
WHY_OTHERS = "other people are on it, and Google emails them"
WHY_ORGANISER = "you're not its organiser"
WHY_KIND = "JARVIS can't recreate this kind of event"
WHY_REPEATS = "it repeats, and a restore would lose its changed occurrences"


def _self(event: dict[str, Any], who: str) -> bool:
    person = event.get(who)
    return isinstance(person, dict) and person.get("self") is True


def _owner_organises(event: dict[str, Any]) -> bool:
    return _self(event, "organizer")


def owner_authored(event: dict[str, Any]) -> bool:
    """The owner's own words: plan D8's one rule (`provenance.is_owner_authored_event`)."""
    return is_owner_authored_event(event)


def delete_risk(event: dict[str, Any]) -> tuple[ActionRisk, str]:
    """(R2, "") when deleting this event can be undone; else (R3, why not, in plain words)."""
    if others_on(event):
        return ActionRisk.IRREVERSIBLE, WHY_OTHERS
    if not _owner_organises(event):
        return ActionRisk.IRREVERSIBLE, WHY_ORGANISER
    if str(event.get("eventType") or "default") not in ORDINARY_TYPES:
        return ActionRisk.IRREVERSIBLE, WHY_KIND
    if (event.get("recurrence") or event.get("recurringEventId")) and not is_reminder(event):
        return ActionRisk.IRREVERSIBLE, WHY_REPEATS
    return ActionRisk.REVERSIBLE, ""


def restore_body(snapshot: dict[str, Any]) -> dict[str, Any]:
    """The insert body: only the restorable fields (never attendees, ids or links)."""
    body = {k: copy.deepcopy(snapshot[k]) for k in _RESTORED if k in snapshot}
    rule = snapshot.get("recurrence")
    if isinstance(rule, list) and all(isinstance(x, str) for x in rule) and is_reminder(snapshot):
        body["recurrence"] = list(rule)
    return body


def event_snapshot(event: dict[str, Any]) -> dict[str, Any]:
    return restore_body({**event, "recurrence": event.get("recurrence")})


@dataclass(frozen=True)
class CalendarRestorer:
    conn: GoogleConnector
    events_url: str

    async def restore(
        self, uid: str, snapshot: dict[str, Any], *, outside: bool = False
    ) -> Restored:
        """`outside`: the kept event was not the owner's own (D8) — the new copy is marked."""
        body = restore_body(snapshot)
        if not isinstance(body.get("start"), dict) or not isinstance(body.get("end"), dict):
            raise GoogleAPIError("The kept copy has no time, so the event can't be recreated.")
        if outside:
            body = mark_outside(body)
        e = await self.conn.request(
            uid, "POST", self.events_url, params={"sendUpdates": "none"}, json=body
        )
        new_id = one_line(e.get("id") if isinstance(e, dict) else None, 1024)
        if not new_id:
            raise GoogleAPIError("Google did not confirm the restored event.")
        return Restored(new_id=new_id)


async def delete_kept(
    conn: GoogleConnector, undo: UndoBin, url: str, event: dict[str, Any], source: str
) -> Any:
    """Delete `event` (just re-read): undo-able → copy kept FIRST (none kept → nothing deleted),
    then deleted with nobody notified; not undo-able → only when the owner approved it. The
    result is vouched for (D8) when the event was the owner's own."""
    ctx = require_tool_context()
    risk, _ = delete_risk(event)
    mine = owner_authored(event)
    if risk is ActionRisk.IRREVERSIBLE:
        if not ctx.confirmed:
            raise RuntimeError(CHANGED)
        await conn.request(ctx.user_id, "DELETE", url, params={"sendUpdates": "all"})
        return vouch({"deleted": True, "id": one_line(event.get("id"), 1024)}, mine)
    title = str(event.get("summary") or "(no title)")
    item = await undo.keep(ctx.user_id, "event", title, event_snapshot(event), owner_authored=mine)
    try:
        await conn.request(ctx.user_id, "DELETE", url, params={"sendUpdates": "none"})
    except Exception:
        await undo.discard(ctx.user_id, item.id)  # not deleted: no "undo" for it
        raise
    return vouch(deleted_result(item, source=source), item.owner_authored)


__all__ = [
    "CalendarRestorer",
    "delete_kept",
    "delete_risk",
    "event_snapshot",
    "owner_authored",
    "restore_body",
]
