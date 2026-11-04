# src/jarvis/family/service.py
"""Family calendars (R1 D15): register, read, free slots, and (R3) add an event.

The owner registers up to 8 calendars that members shared with him. Adding verifies with
`GET calendarList/{id}` (stores the access role), falling back to `GET calendars/{id}` for a
calendar shared but not in his list (taken as `reader`: that call carries no role). No new scope:
`calendar.readonly` / `calendar.events` are already requested. Every call goes through
`GoogleConnector.request`. Titles, places and descriptions are other people's words: fenced, never
vouched. A `freeBusyReader` member yields busy blocks only (no titles exist to show). Writes to a
family calendar are R3 and only with writer / owner access (re-checked live when the card runs).
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from jarvis.family.models import (
    ACCESS_LEVELS,
    CALENDAR_ID,
    ID_MAX,
    NAME_MAX,
    Member,
)
from jarvis.family.store import FamilyDuplicate, FamilyFull, FamilyStore
from jarvis.integrations.google import (
    GoogleAPIError,
    GoogleConnector,
    GoogleNotConnected,
    GoogleQuotaExceeded,
    GoogleServiceDisabled,
    GoogleUncertain,
)
from jarvis.logging import get_logger
from jarvis.tools.card import one_line
from jarvis.tools.external import wrap_external
from jarvis.tools.google_calendar import (
    BASE,
    FREEBUSY_URL,
    MAX_EVENTS,
    CalendarAPI,
    _event_time,
    compute_free_slots,
    parse_window,
    parse_working_hours,
    query_arg,
)

log = get_logger(__name__)

NOT_SET_UP = "No family calendar added yet — Integrations → Family calendars."
NOT_SHARED = (
    "Not shared with you yet — ask them: Google Calendar → Settings → Share with specific people."
)
LIST_URL = f"{BASE}/users/me/calendarList"
CALENDARS_URL = f"{BASE}/calendars"
MAX_SLOTS_PER_CALL = 20
TITLE_LIMIT = 200
PLACE_LIMIT = 200


class FamilyError(Exception):
    """A change the owner can act on: `reason` is the machine word, `detail` plain words."""

    def __init__(self, reason: str, detail: str, status: int = 422) -> None:
        super().__init__(detail)
        self.reason, self.detail, self.status = reason, detail, status


def utcnow() -> datetime:
    return datetime.now(UTC)


def _enc(calendar_id: str) -> str:
    return quote(calendar_id, safe="")


def clean_member_name(value: Any) -> str:
    name = one_line(value, NAME_MAX + 1) if isinstance(value, str) else ""
    if not name or len(name) > NAME_MAX:
        raise FamilyError("invalid", f"Give a name of at most {NAME_MAX} characters.")
    return name


def clean_calendar_id(value: Any) -> str:
    cid = value.strip().lower() if isinstance(value, str) else ""
    if not cid or len(cid) > ID_MAX or not CALENDAR_ID.fullmatch(cid):
        raise FamilyError(
            "invalid", "Enter the calendar's address, like anjali@gmail.com (not a link)."
        )
    return cid


class FamilyService:
    def __init__(
        self,
        conn: GoogleConnector,
        store: FamilyStore,
        *,
        default_tz: str = "UTC",
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._conn = conn
        self._store = store
        self._clock = clock
        self._calendar = CalendarAPI(conn, fallback_tz=default_tz)

    # ---- the registered members ---------------------------------------------------------------

    async def members(self, uid: str) -> list[Member]:
        return await self._store.members(uid)

    async def _role(self, uid: str, cid: str) -> str | None:
        """The owner's access role on a calendar, or None when it isn't shared with him."""
        try:
            entry = await self._conn.request(uid, "GET", f"{LIST_URL}/{_enc(cid)}")
            role = entry.get("accessRole") if isinstance(entry, dict) else None
            return role if role in ACCESS_LEVELS else "freeBusyReader"
        except (GoogleNotConnected, GoogleUncertain, GoogleQuotaExceeded, GoogleServiceDisabled):
            raise
        except GoogleAPIError:  # 404 (not in his list) or 403: try the calendar itself
            pass
        try:
            await self._conn.request(uid, "GET", f"{CALENDARS_URL}/{_enc(cid)}")
        except (GoogleNotConnected, GoogleUncertain, GoogleQuotaExceeded, GoogleServiceDisabled):
            raise
        except GoogleAPIError:
            return None
        return "reader"  # calendars.get shows no role; assume the least that can read

    async def add(self, uid: str, name: Any, calendar_id: Any) -> Member:
        label, cid = clean_member_name(name), clean_calendar_id(calendar_id)
        try:
            role = await self._role(uid, cid)
        except GoogleNotConnected as exc:
            raise FamilyError("not_connected", str(exc), 503) from None
        except GoogleAPIError:
            raise FamilyError(
                "unavailable", "Google didn't answer; try again in a moment.", 503
            ) from None
        if role is None:
            raise FamilyError("not_shared", NOT_SHARED)
        now = self._clock().isoformat()
        member = Member(
            id=f"fam_{secrets.token_hex(6)}",
            name=label,
            calendar_id=cid,
            access=role,  # type: ignore[arg-type]
            added_at=now,
            verified_at=now,
        )
        try:
            await self._store.add(uid, member)
        except FamilyFull:
            raise FamilyError("full", "You can add up to 8 family calendars.", 409) from None
        except FamilyDuplicate:
            raise FamilyError(
                "duplicate", "That person or calendar is already added.", 409
            ) from None
        return member

    async def remove(self, uid: str, member_id: str) -> bool:
        return await self._store.remove(uid, member_id)

    @staticmethod
    def pick(members: Sequence[Member], who: Any) -> Member:
        text = who.strip().casefold() if isinstance(who, str) else ""
        for m in members:
            if text and text in (m.id.casefold(), m.name.casefold()):
                return m
        names = ", ".join(m.name for m in members)
        raise ValueError(f"No family member called that. Your family calendars: {names}.")

    # ---- reading ------------------------------------------------------------------------------

    async def _busy(
        self, uid: str, ids: Sequence[str], start: datetime, end: datetime
    ) -> dict[str, tuple[list[tuple[datetime, datetime]], bool]]:
        """freeBusy for several calendars at once → id -> (busy blocks, readable?)."""
        data = await self._conn.request(
            uid,
            "POST",
            FREEBUSY_URL,
            json={
                "timeMin": start.astimezone(UTC).isoformat(),
                "timeMax": end.astimezone(UTC).isoformat(),
                "items": [{"id": i} for i in ids],
            },
            retry_safe=True,  # a read-only query
        )
        cals = data.get("calendars") if isinstance(data, dict) else None
        out: dict[str, tuple[list[tuple[datetime, datetime]], bool]] = {}
        for i in ids:
            c = (cals or {}).get(i) if isinstance(cals, dict) else None
            if not isinstance(c, dict) or c.get("errors"):
                out[i] = ([], False)
                continue
            blocks = []
            for b in c.get("busy") or []:
                try:
                    blocks.append(
                        (
                            datetime.fromisoformat(str(b["start"]).replace("Z", "+00:00")),
                            datetime.fromisoformat(str(b["end"]).replace("Z", "+00:00")),
                        )
                    )
                except (KeyError, ValueError):
                    continue
            out[i] = (sorted(blocks), True)
        return out

    def _shape_event(self, e: dict[str, Any], tz: ZoneInfo, who: str) -> dict[str, Any]:
        start, all_day = _event_time(e.get("start"), tz)
        end, _ = _event_time(e.get("end"), tz)
        src = f"{who}'s calendar"
        out: dict[str, Any] = {
            "summary": wrap_external(
                str(e.get("summary") or "(no title)"), source=src, limit=TITLE_LIMIT
            ),
            "start": start,
            "end": end,
            "all_day": all_day,
        }
        if e.get("location"):
            out["location"] = wrap_external(str(e["location"]), source=src, limit=PLACE_LIMIT)
        return out

    async def member_events(
        self,
        uid: str,
        m: Member,
        start: datetime,
        end: datetime,
        tz: ZoneInfo,
        query: str | None = None,
    ) -> dict[str, Any]:
        """One member's calendar between two times. Never raises for that calendar alone: a
        calendar Google won't show any more answers `status: unavailable`."""
        base: dict[str, Any] = {"member": m.name, "access": m.access}
        try:
            if m.access == "freeBusyReader":
                busy = (await self._busy(uid, [m.calendar_id], start, end))[m.calendar_id]
                if not busy[1]:
                    return {**base, "status": "unavailable"}
                return {
                    **base,
                    "status": "ok",
                    "busy_only": True,
                    "busy": [
                        {"start": s.astimezone(tz).isoformat(), "end": e.astimezone(tz).isoformat()}
                        for s, e in busy[0]
                    ],
                }
            params: dict[str, Any] = {
                "timeMin": start.isoformat(),
                "timeMax": end.isoformat(),
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": MAX_EVENTS,
            }
            if query:
                params["q"] = query
            data = await self._conn.request(
                uid, "GET", f"{CALENDARS_URL}/{_enc(m.calendar_id)}/events", params=params
            )
        except GoogleNotConnected:
            raise
        except GoogleAPIError:
            return {**base, "status": "unavailable"}
        items = [
            e
            for e in (data.get("items") if isinstance(data, dict) else None) or []
            if isinstance(e, dict) and e.get("status") != "cancelled"
        ][:MAX_EVENTS]
        return {
            **base,
            "status": "ok",
            "busy_only": False,
            "events": [self._shape_event(e, tz, m.name) for e in items],
        }

    async def events(self, uid: str, a: dict[str, Any]) -> dict[str, Any]:
        members = await self.members(uid)
        if not members:
            return {"status": "not_set_up", "message": NOT_SET_UP}
        chosen = [self.pick(members, a["member"])] if a.get("member") else members
        tz = await self._calendar.owner_tz(uid)
        start, end = parse_window(a, tz)
        query = query_arg(a.get("query"))
        rows = await asyncio.gather(
            *(self.member_events(uid, m, start, end, tz, query) for m in chosen)
        )
        return {"time_zone": tz.key, "members": list(rows)}

    async def free_slots(self, uid: str, a: dict[str, Any]) -> dict[str, Any]:
        members = await self.members(uid)
        if not members:
            return {"status": "not_set_up", "message": NOT_SET_UP}
        names = a.get("members")
        if names is None:
            chosen = list(members)
        elif isinstance(names, list) and 1 <= len(names) <= len(members):
            chosen = [self.pick(members, n) for n in names]
        else:
            raise ValueError("members must be a list of family member names")
        tz = await self._calendar.owner_tz(uid)
        start, end = parse_window(a, tz)
        duration = a.get("duration_min")
        if isinstance(duration, bool) or not isinstance(duration, int) or not 1 <= duration <= 1440:
            raise ValueError("duration_min must be between 1 and 1440")
        day_from, day_to = parse_working_hours(a.get("working_hours"))
        ids = ["primary", *(m.calendar_id for m in chosen)]
        got = await self._busy(uid, ids, start, end)
        if not got["primary"][1]:
            raise GoogleAPIError("Google could not show your own calendar just now.")
        used = [m for m in chosen if got[m.calendar_id][1]]
        skipped = [m.name for m in chosen if not got[m.calendar_id][1]]
        pairs = sorted(
            (s.astimezone(tz), e.astimezone(tz))
            for blocks, _ in [got["primary"], *(got[m.calendar_id] for m in used)]
            for s, e in blocks
        )
        slots = compute_free_slots(start, end, pairs, timedelta(minutes=duration), day_from, day_to)
        out: dict[str, Any] = {
            "time_zone": tz.key,
            "members_included": [m.name for m in used],
            "slots": [
                {"start": s.isoformat(), "end": e.isoformat()}
                for s, e in slots[:MAX_SLOTS_PER_CALL]
            ],
        }
        if skipped:
            out["members_unavailable"] = skipped
        return out

    # ---- writing (R3) -------------------------------------------------------------------------

    async def check_writer(self, uid: str, member_ref: Any) -> Member:
        m = self.pick(await self.members(uid), member_ref)
        if not m.can_write:
            raise ValueError(
                f"{m.name} shared their calendar with you for viewing only, so JARVIS can't add "
                "events to it. Ask them to give you 'Make changes to events'."
            )
        return m

    async def add_event(self, uid: str, a: dict[str, Any]) -> dict[str, Any]:
        m = await self.check_writer(uid, a.get("member"))
        try:
            live = await self._role(uid, m.calendar_id)
        except GoogleNotConnected:
            raise
        if live not in ("writer", "owner"):
            raise ValueError(f"Your access to {m.name}'s calendar changed; nothing was added.")
        tz = await self._calendar.owner_tz(uid)
        start, end = parse_window(a, tz)
        body: dict[str, Any] = {
            "summary": str(a.get("summary") or "").strip()[:500],
            "start": {"dateTime": start.isoformat(), "timeZone": tz.key},
            "end": {"dateTime": end.isoformat(), "timeZone": tz.key},
        }
        for key in ("location", "description"):
            if a.get(key):
                body[key] = str(a[key])[:5_000]
        e = await self._conn.request(
            uid, "POST", f"{CALENDARS_URL}/{_enc(m.calendar_id)}/events", json=body
        )
        return {
            "status": "added",
            "member": m.name,
            "summary": one_line(body["summary"], TITLE_LIMIT),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "id": one_line(e.get("id") if isinstance(e, dict) else "", 256),
        }


__all__ = ["NOT_SET_UP", "NOT_SHARED", "FamilyError", "FamilyService", "clean_calendar_id"]
