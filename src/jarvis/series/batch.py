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
from collections.abc import Callable, Mapping
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jarvis.core.guardrails import ActionRisk
from jarvis.integrations.google import GoogleAPIError, GoogleConnector, GoogleUncertain
from jarvis.logging import get_logger
from jarvis.series.batch_result import create_result, undo_result
from jarvis.series.calendar import batch_events
from jarvis.tools.base import Preview
from jarvis.tools.calendar_batch import (
    BATCH_ID,
    Batch,
    Made,
    Outcome,
    PlanBook,
    Wanted,
    batch_id,
    changed_by_owner,
    numbered,
    parse,
    same_events,
    signature,
    stamped,
)
from jarvis.tools.calendar_cards import TITLE_LIMIT, batch_card, undo_card
from jarvis.tools.calendar_undo import delete_kept, delete_risk
from jarvis.tools.card import one_line
from jarvis.tools.context import require_tool_context
from jarvis.tools.google_calendar import EVENTS_URL, CalendarAPI, parse_window
from jarvis.tools.provenance import is_owner_authored_event, mark_outside, unwrap, vouch
from jarvis.tools.taint import content_tainted
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
FORGET_TRIES = 2


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
        self._zone = _zone(tz)

    def _conn(self) -> GoogleConnector:
        conn = self._google()
        if conn is None:
            raise GoogleAPIError(NOT_LINKED)
        return conn

    def check(self, a: dict[str, Any]) -> None:
        parse(a, limit=self._limit)

    def _card(self, b: Batch, there: int = 0) -> str:
        """The card's text; it says when the round read other people's words (MEDIUM-3)."""
        events = [w.args for w in b.items]
        return batch_card(
            events,
            prefix=b.prefix,
            plan=b.name,
            there=there,
            outside=content_tainted(),
            tz=self._zone,
        )

    def summarize(self, a: dict[str, Any]) -> str:
        return self._card(parse(a, limit=self._limit))

    async def preview_create(self, a: dict[str, Any]) -> Preview:
        """Before the card: Google must be linked, a followed plan must have room, and the card
        says how many of the list are already there (a retry adds only the rest)."""
        ctx = require_tool_context()
        b = parse(a, limit=self._limit)
        conn = self._conn()
        bid = b.batch or batch_id(ctx.user_id, b)
        have = await batch_events(conn, ctx.user_id, bid)
        there = sum(1 for n, _ in await self._numbered(conn, ctx.user_id, b, have) if n in have)
        if b.name and self._book is not None:
            await self._book.room(ctx.user_id, b.name, len(b.items) - there)
        return Preview(self._card(b, there))

    async def _numbered(
        self,
        api: CalendarAPI | GoogleConnector,
        uid: str,
        b: Batch,
        have: Mapping[int, Mapping[str, Any]],
        tz: ZoneInfo | None = None,
    ) -> list[tuple[int, Wanted]]:
        """The list's numbers in its batch. With an earlier batch's id, an unnumbered item that
        is an event already there keeps that event's number (nothing is added twice)."""
        if not b.batch or not have or all(w.n is not None for w in b.items):
            return numbered(b.items, have, bool(b.batch))
        if not isinstance(api, CalendarAPI):  # the preview: made only when it is needed
            api = CalendarAPI(api, None, self._tz)
        zone = tz or await api.owner_tz(uid)

        def sig_of(w: Wanted) -> str:
            try:
                return signature(api.event_body(dict(w.args), zone, create=True))
            except ValueError:
                return ""

        return numbered(b.items, have, True, same_events(b.items, have, sig_of))

    async def _one(
        self,
        api: CalendarAPI,
        uid: str,
        bid: str,
        n: int,
        w: Wanted,
        tz: ZoneInfo,
        outside: bool,
    ) -> Outcome:
        """Create one item; never raises (its outcome says what happened, in plain words)."""
        conn = api.conn
        try:
            body = api.event_body(dict(w.args), tz, create=True)
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
            have = await batch_events(conn, uid, bid)
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
        api = CalendarAPI(conn, None, self._tz)  # one for the whole batch
        tz = await api.owner_tz(uid)
        bid = b.batch or batch_id(uid, b)
        have = await batch_events(conn, uid, bid)
        items = await self._numbered(api, uid, b, have, tz)
        done = [Outcome(n, "already_there", have[n]) for n, _ in items if n in have]
        todo = [(n, w) for n, w in items if n not in have]
        if b.name and self._book is not None:
            try:
                await self._book.room(uid, b.name, len(todo))
            except ValueError as exc:  # checked before the card too; nothing was added
                return {"created": 0, "refused": True, "message": str(exc)}
        for i in range(0, len(todo), PARALLEL):
            chunk = todo[i : i + PARALLEL]
            done += await asyncio.gather(
                *(self._one(api, uid, bid, n, w, tz, ctx.outside) for n, w in chunk)
            )
        done = sorted(await self._settle(conn, uid, bid, done), key=lambda o: o.n)
        wanted = dict(items)
        made = [_made(o, wanted[o.n], tz, bid) for o in done if o.event is not None]
        unsure = sum(o.status == "unconfirmed" for o in done)
        note = await self._follow(uid, b, made, ctx.outside, unsure)
        result = create_result(bid, b, done, wanted, note)
        owned = not ctx.outside and all(is_owner_authored_event(o.event) for o in done if o.event)
        return vouch(result, owned)

    async def _follow(
        self, uid: str, b: Batch, made: list[Made], outside: bool, unsure: int = 0
    ) -> str:
        """Remember a followed plan's sessions. The events are already in the calendar, so a
        failure here is reported in the result and never undoes them. Events Google did not
        confirm are not followed until a retry finds them (said, never hidden)."""
        if not b.name or self._book is None:
            return ""
        later = (
            f" {unsure} event{' ' if unsure == 1 else 's '}Google didn't confirm "
            f"{'is' if unsure == 1 else 'are'} not followed yet: retrying finds and adds "
            f"{'it' if unsure == 1 else 'them'}."
            if unsure
            else ""
        )
        if not made:
            return later.strip()
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
        return "The plan is followed: JARVIS asks after each session whether it happened." + later

    # ---- undo -----------------------------------------------------------------------------------

    def check_undo(self, a: dict[str, Any]) -> None:
        if not isinstance(a.get("batch"), str) or not BATCH_ID.fullmatch(a["batch"]):
            raise ValueError("batch is not a batch id from a calendar_create_events result")

    async def preview_undo(self, a: dict[str, Any]) -> Preview:
        ctx = require_tool_context()
        have = await batch_events(self._conn(), ctx.user_id, a["batch"])
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
        have = await batch_events(conn, ctx.user_id, a["batch"])
        todo, items = sorted(have.items()), []
        for i in range(0, len(todo), PARALLEL):
            items += await asyncio.gather(
                *(self._remove(conn, bin_, n, e) for n, e in todo[i : i + PARALLEL])
            )
        gone = [str(x["id"]) for x in items if x["status"] == "removed"]
        updated = await self._forgotten(ctx.user_id, gone)
        return undo_result(a["batch"], items, plan_updated=updated)

    async def _forgotten(self, uid: str, gone: list[str]) -> bool:
        """The plan forgets the removed events: tried twice; False (said in the result) when it
        could not, though check-ins still look before they ask (`SeriesService.recheck`)."""
        if not gone or self._book is None:
            return True
        for attempt in range(FORGET_TRIES):
            try:
                await self._book.forget(uid, gone)
                return True
            except Exception as exc:  # noqa: BLE001 - the events are gone; said, never raised
                log.error(
                    "a plan was not updated after an undo",
                    extra={"error": type(exc).__name__, "attempt": attempt + 1},
                )
        return False


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _made(o: Outcome, w: Wanted, tz: ZoneInfo, batch: str) -> Made:
    start, end = parse_window(dict(w.args), tz)
    return Made(
        o.n, one_line((o.event or {}).get("id"), 1024), w.title[:TITLE_LIMIT], start, end, batch
    )


__all__ = ["NOT_LINKED", "NO_BIN", "PARALLEL", "BatchAPI"]
