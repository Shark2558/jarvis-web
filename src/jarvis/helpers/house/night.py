# src/jarvis/helpers/house/night.py
"""Telling a SACHET warning once, and keeping night rings bounded (docs/plans/r11-free-helpers.md
D13; security review M3: a feed whose identifiers mutate must not wake him again and again).

`CapTeller.tell(uid, m, now, n)` -> True (told, now or before) or False (try again next run):
- the CAP identifier's claim (tag `cap`, as before), then, for an urgent `disaster_alert` (the
  one kind that rings at night), the content key's claim (`content_key`: the kind, the fixed
  event word, his district and the onset day), so the same warning under a fresh identifier
  with no `references` is told once, by day or by night. The Met kinds keep D13's own rule (a
  nowcast series told once in 3 hours) and are held or dropped at night anyway;
- by day, or for a kind that doesn't ring at night, the alert goes as before (the alert policy
  rings, holds or drops it, D13);
- at night (the default quiet hours, 23:00-06:30 his time) a `disaster_alert` rings only while
  one of the night's `MAX_NIGHT_RINGS` (3) ring slots is free (a claim each, so a restart or a
  mutating feed cannot add more). Any further one folds into ONE morning summary (a
  `weather_warning`, which the policy holds until the morning) and at most one "more urgent
  warnings: open the SACHET app" ring an hour.
Every claim is leased (`HouseStore.once`): a send no channel took releases its claims, so the
item stays queued and the next run tries again. Texts are fixed templates (`words`).
"""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import datetime, timedelta

from jarvis.alerts import AlertKind
from jarvis.helpers.house import words
from jarvis.helpers.house.cap import norm
from jarvis.helpers.house.guard import Counts, tally
from jarvis.helpers.house.store import HouseStore
from jarvis.helpers.ports import HelperContext
from jarvis.notify.models import QuietHours
from jarvis.notify.quiet import in_quiet, local

NIGHT = QuietHours()  # the default quiet hours, 23:00-06:30
MAX_NIGHT_RINGS = 3
TAG = "cap"


def night_of(now: datetime, tz: str) -> str | None:
    """The night `now` falls in (the local day it began), or None by day."""
    if not in_quiet(now, NIGHT, tz):
        return None
    here = local(now, tz)
    began = here.date() if here.hour >= 12 else here.date() - timedelta(days=1)
    return began.isoformat()


def content_key(kind: str, event: str, district: str, day: str) -> str:
    return f"{kind}|{event}|{norm(district)}|{day}"


@dataclass(frozen=True)
class CapMessage:
    ident: str  # the CAP identifier
    kind: AlertKind
    text: str  # a fixed template (words.cap)
    subject: str | None  # the storm gate's key for this warning's root
    key: str  # content_key(...)
    district: str  # his own, for the fold's texts


class CapTeller:
    def __init__(self, ctx: HelperContext, store: HouseStore) -> None:
        self._ctx = ctx
        self._store = store

    async def tell(self, uid: str, m: CapMessage, now: datetime, n: Counts) -> bool:
        def work() -> Awaitable[bool]:
            if m.kind == "disaster_alert":
                return self._by_content(uid, m, now, n)
            return self._ring(uid, m, now, n)

        got = await self._store.once(uid, TAG, m.ident, now, work)
        return got in ("done", "told")

    async def plain(
        self, uid: str, ident: str, kind: AlertKind, text: str, now: datetime, n: Counts
    ) -> bool:
        """Once per CAP identifier, no content key and no night slot (a "lifted" note)."""
        got = await self._store.once(
            uid, TAG, ident, now, lambda: self._send(uid, kind, text, None, now, n)
        )
        return got in ("done", "told")

    async def _by_content(self, uid: str, m: CapMessage, now: datetime, n: Counts) -> bool:
        got = await self._store.once(
            uid, TAG, f"key|{m.key}", now, lambda: self._ring(uid, m, now, n)
        )
        if got == "told":
            n.add("same")  # the same warning under another identifier
        return got in ("done", "told")

    async def _ring(self, uid: str, m: CapMessage, now: datetime, n: Counts) -> bool:
        night = night_of(now, self._ctx.tz) if m.kind == "disaster_alert" else None
        if night is None:
            return await self._send(uid, m.kind, m.text, m.subject, now, n)
        for slot in range(MAX_NIGHT_RINGS):
            got = await self._store.once(
                uid,
                TAG,
                f"night|{night}|{slot}",
                now,
                lambda: self._send(uid, m.kind, m.text, m.subject, now, n),
            )
            if got in ("done", "again"):
                return got == "done"
        return await self._fold(uid, m, night, now, n)

    async def _fold(self, uid: str, m: CapMessage, night: str, now: datetime, n: Counts) -> bool:
        summary = words.night_summary(m.district)
        got = await self._store.once(
            uid,
            TAG,
            f"summary|{night}",
            now,
            lambda: self._send(uid, "weather_warning", summary, None, now, n),
        )
        if got in ("again", "held"):
            return False
        hour = local(now, self._ctx.tz).strftime("%H")
        more, subject = words.night_more(m.district), f"cap:more:{night}:{hour}"
        await self._store.once(
            uid,
            TAG,
            f"more|{night}|{hour}",
            now,
            lambda: self._send(uid, "disaster_alert", more, subject, now, n),
        )
        n.add("folded")
        return True

    async def _send(
        self,
        uid: str,
        kind: AlertKind,
        text: str,
        subject: str | None,
        now: datetime,
        n: Counts,
    ) -> bool:
        got = await self._ctx.sender.send(uid, kind, text, due=now, subject=subject)
        return tally(got, n)


__all__ = ["MAX_NIGHT_RINGS", "NIGHT", "CapMessage", "CapTeller", "content_key", "night_of"]
