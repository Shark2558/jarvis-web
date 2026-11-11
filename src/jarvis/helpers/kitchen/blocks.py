# src/jarvis/helpers/kitchen/blocks.py
"""Cooking and washing-up blocks in his calendar (docs/plans/r11-free-helpers.md D15, item 16).

`calendar_kitchen_blocks` is R2 with `ask_when` always: whatever his rows say (even "Allow"), the
gateway turns every call into an approval card first, and the card's text is written by code from
the arguments (`card_text`). Only the approved card runs, and it writes through the existing
Calendar client (`tools.google_calendar`: his primary calendar, his calendar's time zone, the
connector) the way `calendar_create_event` does: no attendees, `sendUpdates=none`, marked
"outside" when the card was proposed after reading other people's words (`tools.provenance`).
It adds repeating events ("Cooking 19:00-19:45", "Washing-up 20:30-20:45", every day or on the
days he chose, from tomorrow or the day he names). He removes them with the calendar's own delete
(Recently deleted keeps a copy). It sits in the "Add and change your events" row
(`calendar_*` at R2); the Kitchen row governs the plan he keeps, not the calendar.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from jarvis.core.guardrails import ActionRisk
from jarvis.helpers.kitchen.models import DAYS, BlockPlan
from jarvis.integrations.google import GoogleAPIError, GoogleConnector
from jarvis.notify.quiet import local
from jarvis.tools.base import Tool
from jarvis.tools.card import one_line
from jarvis.tools.context import require_tool_context
from jarvis.tools.google_calendar import EVENTS_URL, CalendarAPI
from jarvis.tools.provenance import is_owner_authored_event, mark_outside, vouch

TOOL = "calendar_kitchen_blocks"
ONLY = ("both", "cooking", "washing_up")
MAX_AHEAD_DAYS = 365
LABEL = {"cooking": "Cooking", "washing_up": "Washing-up"}
DESCRIPTION = "Blocked by JARVIS from your Kitchen plan."
_ALIASES = {
    **{d: d for d in DAYS},
    "monday": "mon", "tues": "tue", "tuesday": "tue", "wednesday": "wed", "thur": "thu",
    "thurs": "thu", "thursday": "thu", "friday": "fri", "saturday": "sat", "sunday": "sun",
}  # fmt: skip
_EVERY_DAY = frozenset({"", "daily", "every day", "everyday", "all", "all days"})
_RRULE_DAY = {d: d[:2].upper() for d in DAYS}
_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


@dataclass(frozen=True)
class Plan:
    blocks: tuple[tuple[str, str, int], ...]  # (kind, HH:MM, minutes)
    days: tuple[str, ...]  # () = every day
    start: date | None


def _minutes(value: object, name: str) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise ValueError(f"{name} must be a whole number of minutes")
    text = str(value).strip()
    if not text.isdigit():
        raise ValueError(f"{name} must be a whole number of minutes")
    return int(text)


def _days(value: object) -> tuple[str, ...]:
    text = one_line(value or "", 80).casefold()
    if text in _EVERY_DAY:
        return ()
    words = [w for w in re.split(r"[\s,;/]+", text) if w and w != "and"]
    days = {_ALIASES.get(w) for w in words}
    if None in days or not days:
        raise ValueError("days are words like 'mon, wed, fri', or 'daily'")
    return tuple(d for d in DAYS if d in days)


def _start(value: object) -> date | None:
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ValueError("start must read YYYY-MM-DD") from None


def parse_args(a: Mapping[str, Any]) -> Plan:
    only = a.get("only") or "both"
    if only not in ONLY:
        raise ValueError("only is both, cooking or washing_up")
    days = _days(a.get("days"))
    given = {
        "cooking_at": a.get("cooking_at") or None,
        "cooking_minutes": _minutes(a.get("cooking_minutes"), "cooking_minutes"),
        "washing_at": a.get("washing_at") or None,
        "washing_minutes": _minutes(a.get("washing_minutes"), "washing_minutes"),
    }
    try:
        p = BlockPlan.model_validate(
            {**{k: v for k, v in given.items() if v is not None}, "days": days}
        )
    except ValidationError:
        raise ValueError(
            "times read HH:MM; cooking is 10 to 180 minutes, washing-up 5 to 90"
        ) from None
    blocks = []
    if only in ("both", "cooking"):
        blocks.append(("cooking", p.cooking_at, p.cooking_minutes))
    if only in ("both", "washing_up"):
        blocks.append(("washing_up", p.washing_at, p.washing_minutes))
    return Plan(tuple(blocks), p.days, _start(a.get("start")))


def _span(at: str, minutes: int) -> str:
    start = datetime.combine(date(2000, 1, 1), time.fromisoformat(at))
    return f"{at}-{(start + timedelta(minutes=minutes)).strftime('%H:%M')}"


def _when(p: Plan) -> str:
    if not p.days:
        when = "every day"
    else:
        names = [d.capitalize() for d in p.days]
        when = "every " + (
            names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        )
    since = (
        "tomorrow"
        if p.start is None
        else f"{p.start.day} {_MONTHS[p.start.month - 1]} {p.start.year}"
    )
    return f"{when} from {since}"


def _parts(p: Plan) -> str:
    return " and ".join(f"{LABEL[k]} {_span(at, m)}" for k, at, m in p.blocks)


def card_text(a: Mapping[str, Any]) -> str:
    """The approval card, by code from the arguments only (no I/O)."""
    p = parse_args(a)
    return f"Add to your calendar, repeating {_when(p)}: {_parts(p)}. Only you are on them."


def _first(start: date, days: tuple[str, ...]) -> date:
    if not days:
        return start
    return next(
        start + timedelta(n) for n in range(7) if DAYS[(start + timedelta(n)).weekday()] in days
    )


def _body(
    kind: str, at: str, minutes: int, first: date, tz: ZoneInfo, days: tuple[str, ...]
) -> dict[str, Any]:
    begin = datetime.combine(first, time.fromisoformat(at), tzinfo=tz)
    end = begin + timedelta(minutes=minutes)
    rule = (
        "RRULE:FREQ=DAILY"
        if not days
        else "RRULE:FREQ=WEEKLY;BYDAY=" + ",".join(_RRULE_DAY[d] for d in days)
    )
    return {
        "summary": LABEL[kind],
        "description": DESCRIPTION,
        "start": {"dateTime": begin.isoformat(), "timeZone": tz.key},
        "end": {"dateTime": end.isoformat(), "timeZone": tz.key},
        "recurrence": [rule],
        "transparency": "opaque",
    }


class BlocksAPI:
    def __init__(self, conn: GoogleConnector, *, tz: str, now: Callable[[], datetime]) -> None:
        self._conn = conn
        self._calendar = CalendarAPI(conn, fallback_tz=tz)
        self._tz = tz
        self._now = now

    def check(self, a: dict[str, Any]) -> None:
        p = parse_args(a)
        today = local(self._now(), self._tz).date()
        if p.start is not None and not today <= p.start <= today + timedelta(MAX_AHEAD_DAYS):
            raise ValueError("start must be from today to a year ahead")

    async def run(self, a: dict[str, Any]) -> Any:
        ctx = require_tool_context()
        p = parse_args(a)
        tz = await self._calendar.owner_tz(ctx.user_id)
        first = _first(p.start or local(self._now(), tz.key).date() + timedelta(1), p.days)
        made: list[dict[str, Any]] = []
        for kind, at, minutes in p.blocks:
            body = _body(kind, at, minutes, first, tz, p.days)
            if ctx.outside:
                body = mark_outside(body)
            try:
                e = await self._conn.request(
                    ctx.user_id, "POST", EVENTS_URL, params={"sendUpdates": "none"}, json=body
                )
            except GoogleAPIError:
                if not made:
                    raise
                break
            made.append({"id": one_line(e.get("id"), 1024), "kind": kind, "event": e})
        owned = not ctx.outside and all(is_owner_authored_event(m["event"]) for m in made)
        created = [{"id": m["id"], "kind": m["kind"]} for m in made]
        return vouch(self._result(p, first, created), owned)

    @staticmethod
    def _result(p: Plan, first: date, made: list[dict[str, Any]]) -> dict[str, Any]:
        shown = Plan(p.blocks, p.days, first)
        if len(made) == len(p.blocks):
            message = f"Added to your calendar, Sir: {_parts(p)}, {_when(shown)}."
        else:
            missing = LABEL[p.blocks[-1][0]]
            added = _parts(Plan(p.blocks[:1], p.days, first))
            message = f"Added {added}; {missing} couldn't be added just now, Sir."
        return {"created": made, "message": message}


def blocks_tool(conn: GoogleConnector, *, tz: str, now: Callable[[], datetime]) -> Tool:
    api = BlocksAPI(conn, tz=tz, now=now)
    hhmm = {"type": "string", "pattern": r"^\d{2}:\d{2}$", "description": "HH:MM, 24-hour"}
    return Tool(
        TOOL,
        "Propose repeating cooking and washing-up blocks in the owner's calendar (always an "
        "approval card first; nothing is added until he approves). Defaults: cooking 19:00 for "
        "45 minutes, washing-up 20:30 for 15 minutes, every day from tomorrow. days: 'daily' or "
        "'mon, wed, fri'. only: both, cooking or washing_up.",
        {
            "type": "object",
            "properties": {
                "only": {"type": "string", "enum": list(ONLY)},
                "cooking_at": hhmm,
                "cooking_minutes": {"type": "integer", "minimum": 10, "maximum": 180},
                "washing_at": hhmm,
                "washing_minutes": {"type": "integer", "minimum": 5, "maximum": 90},
                "days": {"type": "string", "maxLength": 80},
                "start": {"type": "string", "description": "YYYY-MM-DD; default tomorrow"},
            },
        },
        ActionRisk.REVERSIBLE,
        api.run,
        agent="google",
        check=api.check,
        summarize=card_text,
        ask_when=lambda _a: True,
        activity_words="Cooking and washing-up blocks proposed",
    )


__all__ = ["TOOL", "BlocksAPI", "blocks_tool", "card_text", "parse_args"]
