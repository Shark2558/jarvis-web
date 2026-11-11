# src/jarvis/helpers/today/birthdays.py
"""Birthdays from his Google Contacts (docs/plans/r11-free-helpers.md D8, item 7). Plain code.

`GET https://people.googleapis.com/v1/people/me/connections?personFields=names,birthdays`
(`pageSize` ≤ 1,000, at most 2 pages) under the existing `contacts.readonly` Grant — no new Grant;
`contacts.client.ContactsClient.require` says whether he is linked and granted (the stored link).

- Every read takes the gateway's governed path (I1, `jarvis.tools.background`, `ctx.reads`): the
  gateway's policy and his Contacts row (`contacts_birthdays` is in it) decide. The morning job,
  the brief and the tab read on "Allow" only; the console's `contacts_birthdays`, a call the
  gateway decided (its card, then his OK), reads on "Ask first" too. "Never" is total; unreadable
  rows, no permission service or no gateway: no read. A refused read says why in a fixed line
  ("Birthdays paused: your Contacts permission is set to Ask first. ..."), and a refusal (once a
  day) and each read of Google, a cut one included, leave the one kind-only audit line.
- Only the month and the day are taken: the year (`date.year`) and the free text (`text`, which
  may carry it) are never read, so no year is ever stored, logged, shown or alerted. 29 Feb falls
  on 28 Feb in other years.
- Nothing about a contact is stored (the jobs keep only a claim hash): the day's reading is held in
  memory for that day, so Google is asked about once a day; a failure is asked again after 30
  minutes. A contact's name is other people's words: the tools fence it; alerts name nobody
  unless "names in alerts" is on (`named=`).
"""

from __future__ import annotations

import asyncio
import calendar
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal

from jarvis.contacts.client import (
    GRANT_MSG,
    PEOPLE_OFF_MSG,
    ContactsClient,
    ContactsNotGranted,
)
from jarvis.helpers.paused import PauseCheck, pause_of
from jarvis.integrations.google import (
    NOT_CONNECTED_MSG,
    GoogleAPIError,
    GoogleConnector,
    GoogleNotConnected,
    GoogleServiceDisabled,
)
from jarvis.logging import get_logger
from jarvis.tools.background import UNWIRED, BackgroundReads, Verdict
from jarvis.tools.card import one_line

log = get_logger(__name__)

CONNECTIONS_URL = "https://people.googleapis.com/v1/people/me/connections"
PERSON_FIELDS = "names,birthdays"
PAGE_SIZE = 1000
MAX_PAGES = 2
DEADLINE_S = 8.0
RETRY_AFTER = timedelta(minutes=30)
NAME_LIMIT = 100
TOOL = "contacts_birthdays"
JOB = "birthdays"  # the governed path's job word (the brief and the tools read through it too)
RESOURCE = re.compile(r"^people/[A-Za-z0-9_-]{1,128}$")
WHAT = "Birthdays"  # the "paused" line's words (jarvis.helpers.paused)
UNAVAILABLE_MSG = "Google Contacts couldn't be read just now; JARVIS will try again."
NO_GOOGLE_MSG = "Connect Google in Integrations to see birthdays from your contacts."

State = Literal["ok", "not_connected", "not_granted", "denied", "unavailable"]
OFF_WORDS: dict[type[BaseException], str] = {GoogleServiceDisabled: "service off"}


@dataclass(frozen=True)
class Birthday:
    resource: str
    name: str
    month: int
    day: int

    def falls_on(self, day: date) -> bool:
        if (self.month, self.day) == (day.month, day.day):
            return True
        leap_day = (self.month, self.day) == (2, 29)
        return leap_day and not calendar.isleap(day.year) and (day.month, day.day) == (2, 28)


@dataclass(frozen=True)
class Reading:
    state: State
    people: tuple[Birthday, ...] = ()
    note: str = ""


def _month_day(entry: Any) -> tuple[int, int] | None:
    d = entry.get("date") if isinstance(entry, dict) else None
    if not isinstance(d, dict):
        return None
    m, day = d.get("month"), d.get("day")  # the year is never read
    if (
        isinstance(m, bool)
        or isinstance(day, bool)
        or not isinstance(m, int)
        or not isinstance(day, int)
    ):
        return None
    try:
        date(2000, m, day)  # a leap year: 29 Feb is a real birthday
    except ValueError:
        return None
    return m, day


def _name(p: dict[str, Any]) -> str:
    names = [n for n in p.get("names") or [] if isinstance(n, dict)]
    primary = next((n for n in names if (n.get("metadata") or {}).get("primary") is True), None)
    chosen = primary or (names[0] if names else {})
    raw = chosen.get("displayName")
    return one_line(raw if isinstance(raw, str) else "", NAME_LIMIT)


def birthday_of(p: Any) -> Birthday | None:
    """One contact's birthday (month and day only), or None."""
    if not isinstance(p, dict) or not RESOURCE.fullmatch(str(p.get("resourceName", ""))):
        return None
    found = next((md for b in p.get("birthdays") or [] if (md := _month_day(b))), None)
    name = _name(p)
    if found is None or not name:
        return None
    return Birthday(str(p["resourceName"]), name, found[0], found[1])


async def row_allows(reads: BackgroundReads | None, uid: str, tool: str, job: str) -> Verdict:
    """The gateway's governed path on this read (None: no path, no read); truthy when allowed."""
    return await reads.allowed(uid, tool, job=job) if reads is not None else UNWIRED


def denied_note(v: Verdict) -> str:
    """The fixed line for a refused read (never "switched off": it says the row and its choice)."""
    p = pause_of(WHAT, v)
    return p.line if p is not None else ""


class BirthdayReader:
    def __init__(
        self,
        google: GoogleConnector | None,
        *,
        reads: BackgroundReads | None,
        now: Callable[[], datetime],
        deadline_s: float = DEADLINE_S,
    ) -> None:
        self._google = google
        self._reads = reads
        self._now = now
        self._deadline_s = deadline_s
        self._day: dict[str, tuple[date, Reading]] = {}
        self._failed: dict[str, tuple[datetime, Reading]] = {}

    async def everyone(self, uid: str, day: date) -> Reading:
        """Every contact with a birthday, as of `day` (the governed path is asked every time)."""
        if self._google is None:
            return Reading("not_connected", note=NO_GOOGLE_MSG)
        if not (v := await row_allows(self._reads, uid, TOOL, JOB)):
            return Reading("denied", note=denied_note(v))
        cached = self._day.get(uid)
        if cached is not None and cached[0] == day:
            return cached[1]
        failed = self._failed.get(uid)
        if failed is not None and self._now() < failed[0]:
            return failed[1]
        reading = await self._read(uid)
        if reading.state == "ok":
            self._day[uid] = (day, reading)
            self._failed.pop(uid, None)
        else:
            self._failed[uid] = (self._now() + RETRY_AFTER, reading)
        return reading

    async def on_day(self, uid: str, day: date) -> Reading:
        got = await self.everyone(uid, day)
        return Reading(got.state, tuple(p for p in got.people if p.falls_on(day)), got.note)

    async def upcoming(
        self, uid: str, day: date, days: int
    ) -> tuple[Reading, list[tuple[date, Birthday]]]:
        got = await self.everyone(uid, day)
        out = [
            (d, p)
            for n in range(1, days + 1)
            for p in got.people
            if p.falls_on(d := day + timedelta(days=n))
        ]
        return got, out

    async def _read(self, uid: str) -> Reading:
        assert self._google is not None
        try:
            await ContactsClient(self._google).require(uid)
        except GoogleNotConnected:
            return Reading("not_connected", note=NOT_CONNECTED_MSG)
        except ContactsNotGranted:
            return Reading("not_granted", note=GRANT_MSG)
        assert self._reads is not None  # `everyone` asked the path first
        try:
            async with self._reads.reading(TOOL, job=JOB, words=OFF_WORDS):
                people = await asyncio.wait_for(self._pages(uid), self._deadline_s)
        except GoogleServiceDisabled:
            return Reading("unavailable", note=PEOPLE_OFF_MSG)
        except (GoogleAPIError, GoogleNotConnected, TimeoutError) as exc:
            log.warning("birthdays not read", extra={"error": type(exc).__name__})
            return Reading("unavailable", note=UNAVAILABLE_MSG)
        return Reading("ok", people)

    async def _pages(self, uid: str) -> tuple[Birthday, ...]:
        assert self._google is not None
        found: list[Birthday] = []
        token: str | None = None
        for _ in range(MAX_PAGES):
            params: dict[str, Any] = {"personFields": PERSON_FIELDS, "pageSize": PAGE_SIZE}
            if token:
                params["pageToken"] = token
            body = await self._google.request(uid, "GET", CONNECTIONS_URL, params=params)
            rows = body.get("connections") if isinstance(body, dict) else None
            found += [b for p in rows or [] if (b := birthday_of(p)) is not None]
            nxt = body.get("nextPageToken") if isinstance(body, dict) else None
            token = nxt if isinstance(nxt, str) and nxt else None
            if token is None:
                break
        return tuple(found)


def birthdays_pause(
    reads: BackgroundReads | None, on: Callable[[str], Awaitable[bool]]
) -> PauseCheck:
    """Birthday reminders he switched on (`on(uid)`), paused by his Contacts row."""
    return PauseCheck(reads, what=WHAT, tools=(TOOL,), on=on)


__all__ = [
    "CONNECTIONS_URL",
    "PERSON_FIELDS",
    "TOOL",
    "WHAT",
    "Birthday",
    "BirthdayReader",
    "Reading",
    "birthday_of",
    "birthdays_pause",
    "denied_note",
    "row_allows",
]
