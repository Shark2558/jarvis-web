# src/jarvis/tools/calendar_undo.py
"""Undo-able event deletes (slice 11 D1/D2; Layer 5/6): which deletes can be undone, the copy
kept before one, and how an event comes back.

Risk of a delete (decided on the event as Google has it, by the tool's preview and again when it
runs): R2 — undo-able — for an event only the owner is on, that the owner organises, of the
ordinary kind, and not repeating; a JARVIS reminder (`extendedProperties.private.jarvis ==
"reminder"`, made by the reminder tools) may repeat: its rule comes back with it. Everything else
is R3 (a card and, when the owner requires one, a passkey): Google emails the other people, a
restore can't bring back an organiser's event or a series' changed occurrences, and special event
types (out of office, focus time, …) can't be recreated as they were. A run that finds MORE than
was approved (`ToolContext.allows`: a solo event that gained guests) refuses.

The copy keeps what a restore sends back — summary, description, location, start/end (with
their time zones), reminders, colorId, transparency, visibility, extendedProperties, recurrence
for a reminder, attachments (https links: Drive files) and source — and never attendees, ids or
links; plus the original's id (a restore checks it is really gone) and what can't come back as it
was: a Meet link (a restore asks Google for a NEW one), another app's video link, a gadget.

A restore (slice 11 fix) inserts with an id derived from the undo id (`restore_event_id`), so a
restore repeated after a lost answer gets a 409 and finds the event it already made instead of
making a second one; it never runs while the original is still there (`StillThere`). One deleted
occurrence of a repeating reminder comes back as a one-off at that time (the Calendar API
documents no way to undelete a cancelled occurrence), and the note says so. A repeating event
needs a time zone to expand: a start with only an offset gets the calendar's zone.

Docs checked 2026-11-02: developers.google.com/workspace/calendar/api/v3/reference/events and
…/events/insert (id: base32hex a-v0-9, 5-1024 chars, unique per calendar; conferenceDataVersion=1
+ conferenceData.createRequest; supportsAttachments=true, ≤ 25 attachments, fileUrl required;
source writable; gadgets deprecated; status "cancelled" = deleted; no undelete method).

Each kept copy also records whether the owner wrote the event (`owner_authored`, plan D8).
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jarvis.core.guardrails import ActionRisk
from jarvis.integrations.google import (
    GoogleAPIError,
    GoogleConflict,
    GoogleConnector,
    GoogleNotFound,
)
from jarvis.tools.calendar_alerts import is_reminder
from jarvis.tools.calendar_cards import others_on
from jarvis.tools.card import one_line
from jarvis.tools.context import require_tool_context
from jarvis.tools.undo_delete import delete_after_keep, keep_copy
from jarvis.undo.models import DeletedItem
from jarvis.undo.service import Restored, StillThere, UndoBin
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
MAX_ATTACHMENTS = 25
RESTORE_PREFIX = "jarvis"  # + the undo id's hex: base32hex (a-v, 0-9) as Google requires
# mirrors google_calendar._EVENT_ID (that module imports this one)
_EVENT_ID = re.compile(r"[a-v0-9]{5,1024}(?:_[0-9a-vRTZ]{1,64}){0,4}")
CHANGED = (
    "That event changed since it was checked (it can no longer be undone), so nothing was "
    "deleted. Look it up again and ask the owner."
)
WHY_OTHERS = "other people are on it, and Google emails them"
WHY_ORGANISER = "you're not its organiser"
WHY_KIND = "JARVIS can't recreate this kind of event"
WHY_REPEATS = "it repeats, and a restore would lose its changed occurrences"
OCCURRENCE = "This was one occurrence of a repeating event; the series continues."
MEET_GOES = "Its video link stops working (a restore gets a new one)."
OTHER_VIDEO_GOES = "Its video link stops working (a restore can't bring it back)."
ONE_OFF = (
    "It was one occurrence of a repeating reminder, so it came back as a one-off at that time "
    "(the repeating series itself is unchanged)."
)
NEW_MEET = "It has a video call again, but the video link is new: the old one no longer works."
NO_OTHER_VIDEO = "Its video link from another app could not be recreated."
ATTACHED = "Its attachments are back."
NO_GADGET = "Its gadget (an old Calendar add-on) could not be recreated."
NO_TIME = "The kept copy has no time, so the event can't be recreated."
STILL_THERE = (
    "That event is still on your calendar (it was never deleted), so nothing was restored."
)
GONE_AGAIN = (
    "That event was restored before and the restored copy has been deleted since: restore "
    "that delete from Recently deleted instead."
)


def restore_event_id(undo_id: str) -> str:
    """The id a restore inserts with: the same on every try, so a repeat finds the first."""
    return RESTORE_PREFIX + undo_id.removeprefix("del_")


def _self(event: dict[str, Any], who: str) -> bool:
    person = event.get(who)
    return isinstance(person, dict) and person.get("self") is True


def _owner_organises(event: dict[str, Any]) -> bool:
    return _self(event, "organizer")


def owner_authored(event: dict[str, Any]) -> bool:
    """The owner's own words (plan D8, local rule until the shared helper lands): organised and
    created by the owner, nobody else on it, not an event Gmail made."""
    return (
        _self(event, "organizer")
        and _self(event, "creator")
        and not others_on(event)
        and event.get("eventType") != "fromGmail"
    )


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


# ---- the copy -----------------------------------------------------------------------------------


def _link(value: Any, *schemes: str) -> str:
    text = one_line(value, 2048) if isinstance(value, str) else ""
    return text if text.startswith(schemes) else ""


def _attachments(raw: Any) -> list[dict[str, str]]:
    """Attachments as a restore re-adds them: an https fileUrl (required), title, mimeType."""
    out: list[dict[str, str]] = []
    for a in raw if isinstance(raw, list) else []:
        url = _link(a.get("fileUrl"), "https://") if isinstance(a, dict) else ""
        if not url:
            continue
        att = {"fileUrl": url}
        for key in ("title", "mimeType"):
            if isinstance(a.get(key), str) and a[key]:
                att[key] = one_line(a[key], 300)
        out.append(att)
    return out[:MAX_ATTACHMENTS]


def _source(raw: Any) -> dict[str, str] | None:
    url = _link(raw.get("url"), "https://", "http://") if isinstance(raw, dict) else ""
    if not url:
        return None
    return {"title": one_line(raw.get("title"), 300), "url": url}


def _video(event: dict[str, Any]) -> str:
    """ "meet" (Google Meet: a restore asks for a new one), "other" (another app's), or ""."""
    conf = event.get("conferenceData")
    solution = conf.get("conferenceSolution") if isinstance(conf, dict) else None
    key = solution.get("key") if isinstance(solution, dict) else None
    kind = key.get("type") if isinstance(key, dict) else None
    if event.get("hangoutLink") or kind == "hangoutsMeet":
        return "meet"
    return "other" if conf else ""


def restore_body(snapshot: dict[str, Any]) -> dict[str, Any]:
    """The insert body: only the restorable fields (never attendees, ids or links)."""
    body = {k: copy.deepcopy(snapshot[k]) for k in _RESTORED if k in snapshot}
    rule = snapshot.get("recurrence")
    if isinstance(rule, list) and all(isinstance(x, str) for x in rule) and is_reminder(snapshot):
        body["recurrence"] = list(rule)
    if attachments := _attachments(snapshot.get("attachments")):
        body["attachments"] = attachments
    if (source := _source(snapshot.get("source"))) is not None:
        body["source"] = source
    return body


def event_snapshot(event: dict[str, Any]) -> dict[str, Any]:
    snap = restore_body({**event, "recurrence": event.get("recurrence")})
    snap["origin_id"] = one_line(event.get("id"), 1024)
    if event.get("recurringEventId"):
        snap["occurrence_of"] = one_line(event["recurringEventId"], 1024)
    if video := _video(event):
        snap["video"] = video
    if event.get("gadget"):
        snap["gadget"] = True
    return snap


def delete_note(event: dict[str, Any]) -> str:
    """What else the owner should know about this delete (our words)."""
    parts = [OCCURRENCE] if event.get("recurringEventId") else []
    video = _video(event)
    if video:
        parts.append(MEET_GOES if video == "meet" else OTHER_VIDEO_GOES)
    return " ".join(parts)


def restore_note(snapshot: dict[str, Any]) -> str:
    parts = [ONE_OFF] if snapshot.get("occurrence_of") else []
    if snapshot.get("video") == "meet":
        parts.append(NEW_MEET)
    elif snapshot.get("video"):
        parts.append(NO_OTHER_VIDEO)
    if snapshot.get("attachments"):
        parts.append(ATTACHED)
    if snapshot.get("gadget"):
        parts.append(NO_GADGET)
    return " ".join(parts)


# ---- restore ------------------------------------------------------------------------------------


def _insert_params(snapshot: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {"sendUpdates": "none"}
    if snapshot.get("video") == "meet":
        params["conferenceDataVersion"] = 1
    if body.get("attachments"):
        params["supportsAttachments"] = "true"
    return params


@dataclass(frozen=True)
class CalendarRestorer:
    conn: GoogleConnector
    events_url: str
    tz_url: str

    async def restore(self, uid: str, item: DeletedItem) -> Restored:
        snap = item.snapshot
        body = restore_body(snap)
        if not isinstance(body.get("start"), dict) or not isinstance(body.get("end"), dict):
            raise GoogleAPIError(NO_TIME)
        if await self._still_there(uid, snap.get("origin_id")):
            raise StillThere(STILL_THERE)
        if "recurrence" in body:
            await self._zoned(uid, body)
        if snap.get("video") == "meet":  # never the old link: Google makes a new one
            key = {"type": "hangoutsMeet"}
            body["conferenceData"] = {
                "createRequest": {"requestId": item.id, "conferenceSolutionKey": key}
            }
        rid = restore_event_id(item.id)
        new_id = await self._insert(uid, {**body, "id": rid}, _insert_params(snap, body), rid)
        return Restored(new_id=new_id, note=restore_note(snap))

    async def _still_there(self, uid: str, origin: Any) -> bool:
        """Is the deleted original still on the calendar? (A copy kept before this check
        existed has no origin id: nothing to check.) A failed read fails the restore."""
        if not isinstance(origin, str) or not _EVENT_ID.fullmatch(origin):
            return False
        try:
            e = await self.conn.request(uid, "GET", f"{self.events_url}/{origin}")
        except GoogleNotFound:
            return False
        return isinstance(e, dict) and e.get("status") != "cancelled"

    async def _zoned(self, uid: str, body: dict[str, Any]) -> None:
        """A repeating event's times need a zone (Google expands the rule in it)."""
        parts = [body[k] for k in ("start", "end") if "dateTime" in body[k]]
        if all(p.get("timeZone") for p in parts):
            return
        zone = await self._calendar_zone(uid)
        for k in ("start", "end"):
            if "dateTime" in body[k] and not body[k].get("timeZone"):
                body[k] = {**body[k], "timeZone": zone}

    async def _calendar_zone(self, uid: str) -> str:
        try:
            info = await self.conn.request(uid, "GET", self.tz_url)
            return ZoneInfo(str(info.get("timeZone") or "UTC")).key
        except (GoogleAPIError, ZoneInfoNotFoundError, ValueError, AttributeError):
            return "UTC"

    async def _insert(
        self, uid: str, body: dict[str, Any], params: dict[str, Any], rid: str
    ) -> str:
        try:
            e = await self.conn.request(uid, "POST", self.events_url, params=params, json=body)
        except GoogleConflict:  # an earlier try made it and its answer was lost
            return await self._made_before(uid, rid)
        new_id = one_line(e.get("id") if isinstance(e, dict) else None, 1024)
        if not new_id:
            raise GoogleAPIError("Google did not confirm the restored event.")
        return new_id

    async def _made_before(self, uid: str, rid: str) -> str:
        e = await self.conn.request(uid, "GET", f"{self.events_url}/{rid}")
        if not isinstance(e, dict) or e.get("status") == "cancelled":
            raise GoogleAPIError(GONE_AGAIN)
        return rid


# ---- delete -------------------------------------------------------------------------------------


async def _gone(conn: GoogleConnector, uid: str, url: str) -> bool:
    """Read the event again after a lost answer: deleted (404 / 410 / cancelled) or not."""
    try:
        e = await conn.request(uid, "GET", url)
    except GoogleNotFound:
        return True
    if not isinstance(e, dict):
        raise GoogleAPIError("Google returned no details for that event.")
    return e.get("status") == "cancelled"


async def delete_kept(
    conn: GoogleConnector, undo: UndoBin, url: str, event: dict[str, Any], source: str
) -> dict[str, Any]:
    """Delete `event` (just re-read): undo-able → copy kept FIRST (none kept → nothing deleted),
    then deleted with nobody notified; not undo-able → only on a card approved at that risk."""
    ctx = require_tool_context()
    risk, _ = delete_risk(event)
    if not ctx.allows(risk):
        raise RuntimeError(CHANGED)
    uid = ctx.user_id
    if risk is ActionRisk.IRREVERSIBLE:
        await conn.request(uid, "DELETE", url, params={"sendUpdates": "all"})
        return {"deleted": True, "id": one_line(event.get("id"), 1024)}
    title = str(event.get("summary") or "(no title)")
    snap = event_snapshot(event)
    item = await keep_copy(undo, ctx, "event", title, snap, owner_authored=owner_authored(event))
    done = await delete_after_keep(
        undo,
        uid,
        item.id,
        lambda: conn.request(uid, "DELETE", url, params={"sendUpdates": "none"}),
        lambda: _gone(conn, uid, url),
    )
    return deleted_result(item, source=source, confirmed=done, extra_note=delete_note(event))


__all__ = [
    "CalendarRestorer",
    "delete_kept",
    "delete_note",
    "delete_risk",
    "event_snapshot",
    "owner_authored",
    "restore_body",
    "restore_event_id",
    "restore_note",
]
