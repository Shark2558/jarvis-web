# src/jarvis/series/batch.py
"""`calendar_create_events` and `calendar_undo_events` (R11.1 O2; docs/plans/
r11-1-observations.md D4, D5, D21-A; Layer 5/6, Task & Productivity). The arguments, the markers
and the gathering of single calls are `jarvis.tools.calendar_batch` (pure).

`calendar_create_events`
    R2 with `ask_when` always: whatever the owner's rows say, typed or spoken, tainted round or
    not, it is ONE approval card (one of the message's five) that says how many, the first and
    last date and the prefix; the console lists every event from the card's own arguments.
    Before the card, a read-only look-up makes sure Google is linked and a followed plan has
    room, and counts what is already there. Nothing is created before the approval. Approved,
    the run lists the batch by its marker, then creates only what is missing, five at a time on
    the primary calendar (`sendUpdates=none`): a retry (the same call again, or only the failed
    items with `batch`) never makes an event twice, and a create whose answer was lost is looked
    up the same way. The result is per item; the reply carries one card
    (`reply_cards.BatchCard`) with "Undo all" and, when something failed, "Retry the N". Events
    written from a tainted round carry the outside mark, as single events do. With `series`, the
    plan is remembered through `PlanBook` (`jarvis.series.service`): its sessions are followed.

`calendar_undo_events` {batch}
    R2 with `ask_when` always: when the MODEL asks it is a card like any other write (it may
    remove hundreds of events). It deletes the batch's events the owner has not changed since,
    each through the existing undo-able delete (a copy in Recently deleted, 30 days); an event
    that gained guests or repeats now is left to him. The owner's own "Undo all" press runs it
    without a second card through the gateway (`api/fix_plan.py`: the card is proposed and
    approved in the one request), never another way.

`google` / `undo` are read when a call runs: the app builds them around this part.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any
from zoneinfo import ZoneInfo

from jarvis.core.guardrails import ActionRisk
from jarvis.integrations.google import GoogleAPIError, GoogleConnector, GoogleUncertain
from jarvis.logging import get_logger
from jarvis.series.batch_result import create_result, undo_result
from jarvis.tools.base import Preview, Tool
from jarvis.tools.calendar_batch import (
    BATCH_ID,
    BATCH_ID_KEY,
    CREATE,
    NAME_MAX,
    PREFIX_MAX,
    UNDO,
    Batch,
    Made,
    Outcome,
    PlanBook,
    Wanted,
    batch_id,
    changed_by_owner,
    number_of,
    numbered,
    parse,
    stamped,
)
from jarvis.tools.calendar_cards import TITLE_LIMIT, batch_card, undo_card
from jarvis.tools.calendar_undo import delete_kept, delete_risk
from jarvis.tools.card import one_line
from jarvis.tools.context import require_tool_context
from jarvis.tools.google_calendar import EVENTS_URL, CalendarAPI, parse_window
from jarvis.tools.provenance import is_owner_authored_event, mark_outside, unwrap, vouch
from jarvis.undo.service import UndoBin

log = get_logger(__name__)

PARALLEL = 5  # creates (and deletes) at a time (D5)
PAGE = 250
MAX_PAGES = 4  # a batch's events listed by its marker: at most 1,000
NOT_LINKED = "Google is not linked, Sir. Link it in Integrations, then ask again."
NO_BIN = (
    "Recently deleted is not available on this server, Sir, so I won't remove events in bulk. "
    "Delete them in Google Calendar."
)
CHANGED_WHY = "you changed it"
UNSURE_WHY = "Google didn't confirm it; check your calendar before retrying"
FAILED_WHY = "it could not be added"


class BatchAPI:
    """`google` / `undo` are read when a call runs (the app builds them around this part)."""

    def __init__(
        self,
        google: Callable[[], GoogleConnector | None],
        undo: Callable[[], UndoBin | None],
        *,
        limit: int,
        tz: str,
        book: PlanBook | None = None,
    ) -> None:
        self._google, self._undo = google, undo
        self._limit, self._tz, self._book = limit, tz, book

    def _conn(self) -> GoogleConnector:
        conn = self._google()
        if conn is None:
            raise GoogleAPIError(NOT_LINKED)
        return conn

    def check(self, a: dict[str, Any]) -> None:
        parse(a, limit=self._limit)

    def summarize(self, a: dict[str, Any]) -> str:
        b = parse(a, limit=self._limit)
        return batch_card([w.args for w in b.items], prefix=b.prefix, plan=b.name)

    async def _existing(
        self, conn: GoogleConnector, uid: str, batch: str
    ) -> dict[int, dict[str, Any]]:
        """The batch's events now in the calendar, by item number (listed by the marker)."""
        found: dict[int, dict[str, Any]] = {}
        params: dict[str, Any] = {
            "privateExtendedProperty": f"{BATCH_ID_KEY}={batch}",
            "maxResults": PAGE,
            "showDeleted": "false",
        }
        for _ in range(MAX_PAGES):
            got = await conn.request(uid, "GET", EVENTS_URL, params=params)
            data = got if isinstance(got, dict) else {}
            for e in data.get("items") or []:
                n = number_of(e, batch) if isinstance(e, dict) else None
                if n is not None and e.get("status") != "cancelled":
                    found.setdefault(n, e)
            token = data.get("nextPageToken")
            if not token:
                break
            params = {**params, "pageToken": token}
        return found

    async def preview_create(self, a: dict[str, Any]) -> Preview:
        """Before the card: Google must be linked, a followed plan must have room, and the card
        says how many of the list are already there (a retry adds only the rest)."""
        ctx = require_tool_context()
        b = parse(a, limit=self._limit)
        conn = self._conn()
        if b.name and self._book is not None:
            await self._book.room(ctx.user_id, b.name, len(b.items))
        bid = b.batch or batch_id(ctx.user_id, b)
        have = await self._existing(conn, ctx.user_id, bid)
        there = sum(1 for n, _ in numbered(b.items, have, bool(b.batch)) if n in have)
        return Preview(
            batch_card([w.args for w in b.items], prefix=b.prefix, plan=b.name, there=there)
        )

    async def _one(
        self,
        conn: GoogleConnector,
        uid: str,
        bid: str,
        n: int,
        w: Wanted,
        tz: ZoneInfo,
        outside: bool,
    ) -> Outcome:
        """Create one item; never raises (its outcome says what happened, in plain words)."""
        try:
            body = CalendarAPI(conn, None, self._tz)._body(dict(w.args), tz, create=True)  # noqa: SLF001
            body = stamped(mark_outside(body) if outside else body, bid, n)
            e = await conn.request(
                uid, "POST", EVENTS_URL, params={"sendUpdates": "none"}, json=body
            )
        except GoogleUncertain:
            return Outcome(n, "unconfirmed", why=UNSURE_WHY)
        except (GoogleAPIError, ValueError) as exc:  # our own plain words, never Google's
            return Outcome(n, "failed", why=one_line(str(exc), 200) or FAILED_WHY)
        except Exception as exc:  # noqa: BLE001 - one item never fails the batch
            log.warning("a batch event wasn't added", extra={"error": type(exc).__name__})
            return Outcome(n, "failed", why=FAILED_WHY)
        return Outcome(n, "created", e if isinstance(e, dict) else {})

    async def _settle(
        self, conn: GoogleConnector, uid: str, bid: str, done: list[Outcome]
    ) -> list[Outcome]:
        """Creates whose answer was lost: look the batch up again by its marker (D5)."""
        if not any(o.status == "unconfirmed" for o in done):
            return done
        try:
            have = await self._existing(conn, uid, bid)
        except GoogleAPIError:
            return done  # can't tell: they stay "unconfirmed", in plain words
        return [
            Outcome(o.n, "created", have[o.n]) if o.status == "unconfirmed" and o.n in have else o
            for o in done
        ]

    async def create(self, a: dict[str, Any]) -> Any:
        ctx = require_tool_context()
        uid, b = ctx.user_id, parse(a, limit=self._limit)
        conn = self._conn()
        if b.name and self._book is not None:
            try:
                await self._book.room(uid, b.name, len(b.items))
            except ValueError as exc:  # checked before the card too; nothing was added
                return {"created": 0, "refused": True, "message": str(exc)}
        tz = await CalendarAPI(conn, None, self._tz).owner_tz(uid)
        bid = b.batch or batch_id(uid, b)
        have = await self._existing(conn, uid, bid)
        items = numbered(b.items, have, bool(b.batch))
        done = [Outcome(n, "already_there", have[n]) for n, _ in items if n in have]
        todo = [(n, w) for n, w in items if n not in have]
        for i in range(0, len(todo), PARALLEL):
            chunk = todo[i : i + PARALLEL]
            done += await asyncio.gather(
                *(self._one(conn, uid, bid, n, w, tz, ctx.outside) for n, w in chunk)
            )
        done = sorted(await self._settle(conn, uid, bid, done), key=lambda o: o.n)
        wanted = dict(items)
        made = [_made(o, wanted[o.n], tz, bid) for o in done if o.event is not None]
        note = await self._follow(uid, b, made, ctx.outside)
        result = create_result(bid, b, done, wanted, note)
        owned = not ctx.outside and all(is_owner_authored_event(o.event) for o in done if o.event)
        return vouch(result, owned)

    async def _follow(self, uid: str, b: Batch, made: list[Made], outside: bool) -> str:
        """Remember a followed plan's sessions. The events are already in the calendar, so a
        failure here is reported in the result and never undoes them."""
        if not b.name or self._book is None or not made:
            return ""
        try:
            await self._book.remember(
                uid, name=b.name, prefix=b.prefix, outside=outside, sessions=made
            )
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            log.error("a plan was not remembered", extra={"error": type(exc).__name__})
            return (
                "The events are in the calendar, but the plan could not be remembered, so its "
                "sessions will not be followed up. Tell the owner."
            )
        return "The plan is followed: JARVIS asks after each session whether it happened."

    # ---- undo -----------------------------------------------------------------------------------

    def check_undo(self, a: dict[str, Any]) -> None:
        if not isinstance(a.get("batch"), str) or not BATCH_ID.fullmatch(a["batch"]):
            raise ValueError("batch is not a batch id from a calendar_create_events result")

    async def preview_undo(self, a: dict[str, Any]) -> Preview:
        ctx = require_tool_context()
        have = await self._existing(self._conn(), ctx.user_id, a["batch"])
        if not have:
            raise LookupError("no events of that batch are in the calendar (already removed?)")
        events = [have[n] for n in sorted(have)]
        kept = sum(1 for e in events if changed_by_owner(e))
        return Preview(undo_card(events, kept=kept))

    async def _remove(
        self, conn: GoogleConnector, bin_: UndoBin, n: int, e: dict[str, Any]
    ) -> dict[str, Any]:
        """Delete one event of the batch through the undo-able delete; never raises."""
        if changed_by_owner(e):
            return {"n": n, "status": "kept", "why": CHANGED_WHY}
        risk, why = delete_risk(e)
        if risk is not ActionRisk.REVERSIBLE:  # it gained guests, or repeats now: his to delete
            return {"n": n, "status": "kept", "why": why}
        try:
            out = await delete_kept(conn, bin_, f"{EVENTS_URL}/{e['id']}", e, "calendar")
        except Exception as exc:  # noqa: BLE001 - one event never fails the undo
            log.warning("a batch event wasn't removed", extra={"error": type(exc).__name__})
            return {"n": n, "status": "failed", "why": "it could not be removed"}
        value, _ = unwrap(out)  # delete_kept vouches for the owner's own event
        return {"n": n, "status": "removed", "undo_id": value.get("undo_id"), "id": e["id"]}

    async def undo(self, a: dict[str, Any]) -> Any:
        ctx = require_tool_context()
        conn, bin_ = self._conn(), self._undo()
        if bin_ is None:
            return {"batch": a["batch"], "removed": 0, "unavailable": True, "message": NO_BIN}
        have = await self._existing(conn, ctx.user_id, a["batch"])
        todo, items = sorted(have.items()), []
        for i in range(0, len(todo), PARALLEL):
            items += await asyncio.gather(
                *(self._remove(conn, bin_, n, e) for n, e in todo[i : i + PARALLEL])
            )
        gone = [str(x["id"]) for x in items if x["status"] == "removed"]
        if gone and self._book is not None:
            try:
                await self._book.forget(ctx.user_id, gone)
            except Exception as exc:  # noqa: BLE001 - the events are gone; the plan catches up
                log.error(
                    "a plan was not updated after an undo", extra={"error": type(exc).__name__}
                )
        return undo_result(a["batch"], items)


def _made(o: Outcome, w: Wanted, tz: ZoneInfo, batch: str) -> Made:
    start, end = parse_window(dict(w.args), tz)
    return Made(
        o.n, one_line((o.event or {}).get("id"), 1024), w.title[:TITLE_LIMIT], start, end, batch
    )


# ---- tools --------------------------------------------------------------------------------------

_ISO = {"type": "string", "description": "ISO 8601 date-time, e.g. 2027-01-15T19:00:00+05:30"}
_EVENT = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "start": _ISO,
        "end": _ISO,
        "description": {"type": "string"},
        "location": {"type": "string"},
        "reminders_minutes": {"type": "array", "items": {"type": "integer"}, "maxItems": 5},
        "n": {"type": "integer", "description": "Its number in the batch; only when retrying."},
    },
    "required": ["summary", "start", "end"],
}


def batch_tools(api: BatchAPI, *, limit: int) -> list[Tool]:
    return [
        Tool(
            CREATE,
            "Add several events to the owner's calendar on ONE approval card that lists them "
            f"all (1 to {limit} events, no guests). More than three events -> this tool, never "
            "many calendar_create_event calls. title_prefix puts '<prefix> - ' before every "
            "title. series {name} makes it a plan JARVIS follows up (it asks after each session "
            "whether it happened). To retry events that failed, send only those with the batch "
            "id from the result. Nothing is added until the owner approves.",
            {
                "type": "object",
                "properties": {
                    "events": {"type": "array", "items": _EVENT, "minItems": 1, "maxItems": limit},
                    "title_prefix": {"type": "string", "maxLength": PREFIX_MAX},
                    "series": {
                        "type": "object",
                        "properties": {"name": {"type": "string", "maxLength": NAME_MAX}},
                        "required": ["name"],
                    },
                    "batch": {"type": "string", "description": "Only when retrying a batch."},
                },
                "required": ["events"],
            },
            ActionRisk.REVERSIBLE,
            api.create,
            agent="google",
            check=api.check,
            summarize=api.summarize,
            preview=api.preview_create,
            ask_when=lambda _a: True,
            may_vouch=True,
            activity_words="Calendar events added in one batch",
        ),
        Tool(
            UNDO,
            "Remove every event of one calendar_create_events batch that the owner has not "
            "changed since (each is kept in Recently deleted for 30 days). The owner approves "
            "it first; an event he changed is left alone.",
            {"type": "object", "properties": {"batch": {"type": "string"}}, "required": ["batch"]},
            ActionRisk.REVERSIBLE,
            api.undo,
            agent="google",
            check=api.check_undo,
            preview=api.preview_undo,
            ask_when=lambda _a: True,
            activity_words="A batch of calendar events removed",
        ),
    ]


__all__ = ["NOT_LINKED", "NO_BIN", "PARALLEL", "BatchAPI", "batch_tools"]
