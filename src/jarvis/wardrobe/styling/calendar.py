# src/jarvis/wardrobe/styling/calendar.py
"""R13 D13, OPS-04, plan review M12 (docs/plans/r13-wardrobe.md): only the calendar he picks, only
the fields he picks.

- Every read (his calendar list for Settings, the `outfit_clock`'s read of the next 48 hours)
  goes through the governed path `tools.background.BackgroundReads` on the `calendar_list_events`
  row: "Allow" only, one kind-only audit line (agent `helpers`, job `outfits`). "Ask first" or
  "Never": no read, and Settings says "Your Calendar permission is <choice>: allow it, or plan by
  hand." No new Google grant: `calendar.readonly` is already required.
- `calendars(uid)`: his calendarList (`fields=items(id,summary,primary)`); each id is offered
  only as a keyed reference (`ref`); `resolve(uid, ref)` accepts only a reference to an id that
  very list returned, so an id he never had is refused. The id is kept sealed (`plans.Choice`)
  and URL-encoded into the path.
- `read(...)`: `events.list` with `singleEvents=true` (Google returns no cancelled events) and
  `fields` naming ONLY id, status, updated, start, end, and the title and location when he let
  JARVIS read them (title on, location off by default); never the description or attendees.
- A title and a location are matched against the rules' words in code, in memory only
  (`entries`): what is kept (`wardrobe_cal/{uid}`, sealed) is each event's keyed fingerprint, its
  times or day, its `updated` stamp, the dress code and occasion found, and outdoor or not. A
  title is never stored, sent or logged.
- `sync(doc, entries, span, ...)` (pure): a new event makes a plan (tentative); a plan he kept
  when he switched this calendar off, never edited (still tentative, not worn), is taken back
  when he picks the same calendar again (code review H2); an edited one
  (its `updated` stamp) refreshes its times and, while tentative, its dress code; a calendar plan
  whose event is missing from a read that covers its window is cancelled: kept as a draft, never
  an `outfit_ready` (D13).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field

from jarvis.helpers.sources import OUTSIDE_TIMEOUT_S
from jarvis.logging import get_logger
from jarvis.tools.background import Verdict
from jarvis.wardrobe.ports import WardrobeContext
from jarvis.wardrobe.styling.plans import MAX_PLANS, Plan, StylingDoc, new_plan_id
from jarvis.wardrobe.styling.reserve import window
from jarvis.wardrobe.styling.rules import Rules
from jarvis.wardrobe.styling.sealed import SealedDoc

log = get_logger(__name__)
TOOL = "calendar_list_events"  # the row every read obeys
JOB = "outfits"
LIST_URL = "https://www.googleapis.com/calendar/v3/users/me/calendarList"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/{cal}/events"
LIST_FIELDS = "items(id,summary,primary)"
AHEAD = timedelta(hours=48)
MAX_EVENTS = 50
CHOICE_WORDS = {"ask_first": "Ask first", "denied": "Never"}
NOT_LINKED = "Google isn't linked: plan by hand."
UNREADABLE = "Your calendar can't be read just now: plan by hand."


def refused_words(v: Verdict) -> str:
    choice = CHOICE_WORDS.get(v.reason)
    if choice is None:
        return UNREADABLE
    return f"Your Calendar permission is {choice}: allow it, or plan by hand."


def event_fields(fields: tuple[str, ...]) -> str:
    wanted = ["id", "status", "updated", "start", "end"]
    wanted += [
        name for flag, name in (("title", "summary"), ("location", "location")) if flag in fields
    ]
    return f"items({','.join(wanted)})"


class _M(BaseModel):
    # Sealed records (code review M8, security review M2 and L6): a field a later release adds is
    # ignored, so a rollback still opens the document; a bad value never echoes into an error.
    model_config = ConfigDict(frozen=True, extra="ignore", hide_input_in_errors=True)


class CalEntry(_M):
    """One event as kept (never a title, a location, a description or a guest)."""

    k: str = Field(pattern=r"^[0-9a-f]{16}$")
    s: datetime | None = None
    e: datetime | None = None
    d: date | None = None  # an all-day event's day
    u: str = Field(default="", max_length=40)
    code: str
    occ: str | None = None
    out: bool | None = None


class CalDoc(_M):
    read_at: datetime | None = None
    start: datetime | None = None
    end: datetime | None = None
    entries: tuple[CalEntry, ...] = Field(default=(), max_length=MAX_EVENTS)


@dataclass(frozen=True)
class CalItem:
    """One event as read: its title and location live only in memory, for the rules' words."""

    ident: str
    start: datetime | None
    end: datetime | None
    day: date | None
    updated: str
    title: str
    location: str


def _when(raw: Any) -> tuple[datetime | None, date | None]:
    if not isinstance(raw, dict):
        return None, None
    if isinstance(raw.get("dateTime"), str):
        try:
            at = datetime.fromisoformat(raw["dateTime"].replace("Z", "+00:00"))
        except ValueError:
            return None, None
        return (at if at.tzinfo else at.replace(tzinfo=UTC)), None
    if isinstance(raw.get("date"), str):
        try:
            return None, date.fromisoformat(raw["date"])
        except ValueError:
            return None, None
    return None, None


def to_item(raw: Any) -> CalItem | None:
    if not isinstance(raw, dict) or raw.get("status") == "cancelled":
        return None
    ident = raw.get("id")
    (start, day), (end, _) = _when(raw.get("start")), _when(raw.get("end"))
    if not isinstance(ident, str) or (start is None and day is None):
        return None
    if start is not None and (end is None or end <= start):
        return None
    title, place = str(raw.get("summary") or "")[:200], str(raw.get("location") or "")[:200]
    return CalItem(ident, start, end, day, str(raw.get("updated") or "")[:40], title, place)


class Calendar:
    def __init__(self, ctx: WardrobeContext, rules: Rules, sealed: SealedDoc[CalDoc]) -> None:
        self._ctx, self._rules, self.sealed = ctx, rules, sealed

    def ref(self, uid: str, cal_id: str) -> str:
        ring = self._ctx.keyring
        if ring is None:
            return ""
        return ring.mac("wardrobe", f"outfits/calendar/{uid}/{cal_id}")[:16]

    def key(self, uid: str, cal_id: str, event_id: str) -> str:
        ring = self._ctx.keyring
        assert ring is not None  # C is off without a key
        return ring.mac("wardrobe", f"outfits/event/{uid}/{cal_id}/{event_id}")[:16]

    async def _get(self, uid: str, url: str, params: dict[str, Any]) -> Any | str:
        google, reads = self._ctx.state("google"), self._ctx.reads()
        if google is None:
            return NOT_LINKED
        if reads is None:
            return UNREADABLE
        verdict = await reads.allowed(uid, TOOL, job=JOB)
        if not verdict:
            return refused_words(verdict)
        try:
            async with reads.reading(TOOL, job=JOB):
                call = google.request(uid, "GET", url, params=params)
                return await asyncio.wait_for(call, OUTSIDE_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 - no calendar this time; the class in the log
            log.warning("outfits: calendar not read", extra={"error": type(exc).__name__})
            return UNREADABLE

    async def calendars(self, uid: str) -> tuple[list[tuple[str, str, str, bool]], str]:
        """([(ref, id, his calendar's name, primary)], why none): the name is shown live only."""
        got = await self._get(uid, LIST_URL, {"fields": LIST_FIELDS})
        if isinstance(got, str):
            return [], got
        items = got.get("items") if isinstance(got, dict) else None
        out = []
        for raw in items if isinstance(items, list) else []:
            ident = raw.get("id") if isinstance(raw, dict) else None
            if isinstance(ident, str) and 0 < len(ident) <= 300:
                name = str(raw.get("summary") or "")[:200]
                out.append((self.ref(uid, ident), ident, name, raw.get("primary") is True))
        return out, ""

    async def resolve(self, uid: str, ref: str) -> tuple[str | None, str]:
        found, why = await self.calendars(uid)
        if why:
            return None, why
        match = next((ident for r, ident, _, _ in found if r == ref), None)
        return match, "" if match else "That calendar isn't in your list."

    async def read(
        self, uid: str, cal_id: str, fields: tuple[str, ...], start: datetime, end: datetime
    ) -> list[CalItem] | str:
        params = {
            "timeMin": start.astimezone(UTC).isoformat(),
            "timeMax": end.astimezone(UTC).isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": MAX_EVENTS,
            "fields": event_fields(fields),
        }
        got = await self._get(uid, EVENTS_URL.format(cal=quote(cal_id, safe="")), params)
        if isinstance(got, str):
            return got
        items = got.get("items") if isinstance(got, dict) else None
        found = (to_item(i) for i in (items if isinstance(items, list) else [])[:MAX_EVENTS])
        return [i for i in found if i is not None]

    def entries(self, uid: str, cal_id: str, items: list[CalItem]) -> tuple[CalEntry, ...]:
        """What is kept of each event: the rules' answer, never its words."""
        out = []
        for it in items:
            occ = self._rules.occasion_of(it.title) if it.title else None
            out.append(
                CalEntry(
                    k=self.key(uid, cal_id, it.ident),
                    s=it.start,
                    e=it.end,
                    d=it.day,
                    u=it.updated,
                    code=self._rules.code_of(occ, event=True),
                    occ=occ,
                    out=self._rules.outdoor_of(it.location) if it.location else None,
                )
            )
        return tuple(out)


def _plan_of(e: CalEntry, zone: tzinfo, now: datetime) -> Plan:
    day = e.d or (e.s.astimezone(zone).date() if e.s else now.astimezone(zone).date())
    return Plan(
        id=new_plan_id(), day=day, event=e.k, starts=e.s, ends=e.e, code=e.code, occasion=e.occ,
        outdoor=e.out, manual=False, updated=e.u, created_at=now, updated_at=now,
    )  # fmt: skip


def _edited(p: Plan, e: CalEntry, zone: tzinfo, now: datetime) -> Plan:
    fresh = _plan_of(e, zone, now)
    keep = {"code": e.code, "occasion": e.occ} if p.tentative else {}
    return p.model_copy(
        update={"day": fresh.day, "starts": e.s, "ends": e.e, "outdoor": e.out, "updated": e.u,
                "cancelled": False, "updated_at": now, **keep}
    )  # fmt: skip


def sync(
    doc: StylingDoc, entries: tuple[CalEntry, ...], span: tuple[datetime, datetime],
    zone: tzinfo, now: datetime,
) -> tuple[StylingDoc, list[str]]:  # fmt: skip
    """(the plans after this read, the ids of plans made or edited: their looks to pick)."""
    seen = {e.k for e in entries}
    touched: list[str] = []
    for e in entries:
        plan = doc.by_event(e.k)
        if plan is not None and plan.manual and plan.tentative and not plan.worn:
            plan = plan.model_copy(update={"manual": False})  # his calendar again: taken back
            doc, touched = doc.put(plan), [*touched, plan.id]
        if plan is None or plan.manual:
            if plan is None and len(doc.plans) < MAX_PLANS:  # past 60: no more, said in counts
                made = _plan_of(e, zone, now)
                doc, touched = doc.put(made), [*touched, made.id]
            continue
        if plan.updated != e.u or plan.cancelled:
            doc, touched = doc.put(_edited(plan, e, zone, now)), [*touched, plan.id]
    start, end = span
    for plan in doc.plans:
        if plan.manual or plan.event is None or plan.cancelled or plan.event in seen:
            continue
        opens, closes = window(plan, zone)
        if start <= opens and closes <= end:  # the read covered its window: it is gone
            doc = doc.put(plan.model_copy(update={"cancelled": True, "updated_at": now}))
    return doc, touched


def manual_from_now(doc: StylingDoc, now: datetime) -> StylingDoc:
    """His calendar switched off: its plans stay, now his own ("manual"); none is made again."""
    plans = tuple(
        p.model_copy(update={"manual": True, "updated_at": now}) if not p.manual else p
        for p in doc.plans
    )
    return doc.model_copy(update={"plans": plans})


__all__ = [
    "AHEAD",
    "EVENTS_URL",
    "JOB",
    "LIST_FIELDS",
    "LIST_URL",
    "TOOL",
    "CalDoc",
    "CalEntry",
    "CalItem",
    "Calendar",
    "event_fields",
    "manual_from_now",
    "refused_words",
    "sync",
    "to_item",
]
