# src/jarvis/tools/calendar_batch.py
"""Many calendar events as ONE batch (R11.1 O2; docs/plans/r11-1-observations.md D4, D5; Layer
5/6, Task & Productivity): the pure half. The tools themselves (`calendar_create_events`,
`calendar_undo_events`), which talk to Google, are `jarvis.series.batch`.

- `parse`: a batch's arguments {events: [{summary, start, end, description?, location?,
  reminders_minutes?, n?}] (1-`calendar_batch_max`), title_prefix?, series?: {name}, batch?},
  checked before any card. No attendees: an event with guests stays `calendar_create_event` and
  its R3 card.
- The private markers every batch event carries (`stamped`):
      jarvisBatch    "<batch id>:<n>"  which item of which batch (D5)
      jarvisBatchId  "<batch id>"      Events.list filters by an exact value, so the batch alone
                                       needs its own key
      jarvisBatchSig a fingerprint of the title, times, place and notes JARVIS wrote: an event
                     the owner changed since no longer matches it (`changed_by_owner`)
  `batch_id`: the same owner and the same list are the same batch, so a run repeated finds its
  events by the marker and creates nothing twice.
- `gathered`: more than three single `calendar_create_event` calls (no guests) in one round
  become ONE batch call before the gateway sees them, so a model that ignores the batch tool
  still ends in one card that lists everything (O2's root cause: five cards a message, six
  rounds). The Brain calls it around each round (`core.brain._run_calls`).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from jarvis.llm.base import ToolCall
from jarvis.logging import get_logger
from jarvis.tools.base import Tool
from jarvis.tools.calendar_alerts import alert_minutes
from jarvis.tools.card import one_line
from jarvis.tools.gateway import GatewayOutcome, GatewayResult
from jarvis.tools.google_calendar import parse_window
from jarvis.tools.registry import ToolRegistry

log = get_logger(__name__)

CREATE, UNDO, SINGLE = "calendar_create_events", "calendar_undo_events", "calendar_create_event"
MANY = 3  # more single creates than this in one round become one batch card
MAX_NUMBER = 999
BATCH_KEY, BATCH_ID_KEY, SIG_KEY = "jarvisBatch", "jarvisBatchId", "jarvisBatchSig"
PREFIX_MAX, NAME_MAX = 40, 60
DESCRIPTION_MAX, LOCATION_MAX, SUMMARY_MAX = 2_000, 300, 500
ITEM_FIELDS = frozenset(
    {"summary", "start", "end", "description", "location", "reminders_minutes", "n"}
)
BATCH_ID = re.compile(r"b[0-9a-f]{16}")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 .&+'()/-]{0,59}")
_ANY_TZ = ZoneInfo("UTC")
GUESTS = (
    "an event with guests can't go in a batch: create it on its own with calendar_create_event "
    "(the owner approves the invitations)"
)
MERGED = (
    "Not run on its own: more than three events were asked for at once, so this one is on the "
    "single approval card for all of them (see the first result). Do not create it again. Next "
    "time put every event into one calendar_create_events call."
)


class PlanBook(Protocol):
    """Where a followed batch is remembered (`jarvis.series`). `room` raises ValueError, in plain
    words, when the plan can't take `count` more sessions."""

    async def room(self, uid: str, name: str, count: int) -> None: ...

    async def remember(
        self, uid: str, *, name: str, prefix: str, outside: bool, sessions: Sequence[Made]
    ) -> None: ...

    async def forget(self, uid: str, event_ids: Collection[str]) -> None: ...


@dataclass(frozen=True)
class Wanted:
    """One event of a batch as asked for: its number in the batch (None: by position), the
    title it will carry and the arguments `CalendarAPI._body` takes."""

    n: int | None
    title: str
    args: Mapping[str, Any]


@dataclass(frozen=True)
class Batch:
    items: tuple[Wanted, ...]
    prefix: str
    name: str  # the plan to follow ("": none)
    batch: str  # the batch this continues ("": a new one)


@dataclass(frozen=True)
class Made:
    """One event that is in the calendar for a batch item."""

    n: int
    event_id: str
    title: str
    start: datetime
    end: datetime
    batch: str = ""


@dataclass(frozen=True)
class Outcome:
    n: int
    status: str  # created | already_there | failed | unconfirmed
    event: Mapping[str, Any] | None = None
    why: str = ""


# ---- arguments (pure) ---------------------------------------------------------------------------


def title_of(prefix: str, summary: str) -> str:
    """ "<prefix> - <topic>" (D6); a title that already starts with the prefix is left alone."""
    text = " ".join(str(summary).split())[:SUMMARY_MAX]
    if not prefix or text.casefold().startswith(prefix.casefold()):
        return text
    return f"{prefix} - {text}"[:SUMMARY_MAX]


def _text(value: Any, limit: int, what: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{what} must be text")
    if len(value) > limit:
        raise ValueError(f"{what} is too long (at most {limit} characters in a batch)")
    return value


def _item(raw: Any, i: int, prefix: str) -> Wanted:
    if not isinstance(raw, dict):
        raise ValueError(f"event {i} must be an object with summary, start and end")
    if raw.get("attendees"):
        raise ValueError(f"event {i}: {GUESTS}")
    unknown = sorted(set(raw) - ITEM_FIELDS - {"attendees"})
    if unknown:
        raise ValueError(f"event {i}: unknown field {', '.join(unknown)}")
    summary = _text(raw.get("summary"), SUMMARY_MAX, f"event {i}: summary").strip()
    if not summary:
        raise ValueError(f"event {i}: summary is required")
    try:
        parse_window(raw, _ANY_TZ)
    except ValueError as exc:
        raise ValueError(f"event {i}: {exc}") from None
    args: dict[str, Any] = {
        "summary": title_of(prefix, summary),
        "start": raw["start"],
        "end": raw["end"],
    }
    for key, limit in (("description", DESCRIPTION_MAX), ("location", LOCATION_MAX)):
        if raw.get(key):
            args[key] = _text(raw[key], limit, f"event {i}: {key}")
    if raw.get("reminders_minutes") is not None:
        args["reminders_minutes"] = alert_minutes(raw["reminders_minutes"])
    n = raw.get("n")
    if n is not None and (
        isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= MAX_NUMBER
    ):
        raise ValueError(f"event {i}: n must be a whole number from 1 to {MAX_NUMBER}")
    return Wanted(n, args["summary"], args)


def parse(a: Mapping[str, Any], *, limit: int) -> Batch:
    """The batch as asked for, or ValueError in plain words. Pure: run before any card."""
    events = a.get("events")
    if not isinstance(events, list) or not events:
        raise ValueError(f"events must be a list of 1 to {limit} events")
    if len(events) > limit:
        raise ValueError(
            f"too many events for one batch (at most {limit}): make batches of {limit} or fewer"
        )
    prefix = one_line(_text(a.get("title_prefix"), PREFIX_MAX, "title_prefix"), PREFIX_MAX)
    items = tuple(_item(e, i, prefix) for i, e in enumerate(events, 1))
    numbers = [w.n for w in items if w.n is not None]
    if len(set(numbers)) != len(numbers):
        raise ValueError("two events carry the same n")
    series, name = a.get("series"), ""
    if series is not None:
        if not isinstance(series, dict) or set(series) != {"name"}:
            raise ValueError("series must be {name: the plan's name}")
        name = " ".join(_text(series["name"], NAME_MAX, "series name").split())
        if not _NAME.fullmatch(name):
            raise ValueError("series name: letters, digits and spaces, at most 60 characters")
    batch = a.get("batch") or ""
    if batch and (not isinstance(batch, str) or not BATCH_ID.fullmatch(batch)):
        raise ValueError("batch is not a batch id from an earlier calendar_create_events result")
    return Batch(items, prefix, name, batch)


def batch_id(uid: str, batch: Batch) -> str:
    """The same owner and the same list are the same batch: a run repeated creates nothing new."""
    body = json.dumps([w.args for w in batch.items], sort_keys=True, default=str)
    return "b" + hashlib.sha256(f"{uid}\n{batch.name}\n{body}".encode()).hexdigest()[:16]


def _epoch(part: Any) -> str:
    try:
        raw = str(part["dateTime"]).replace("Z", "+00:00")
        return str(int(datetime.fromisoformat(raw).timestamp()))
    except (KeyError, TypeError, ValueError):
        return "?"


def signature(event: Mapping[str, Any]) -> str:
    """A fingerprint of what JARVIS wrote: title, times, place and notes (whitespace-neutral)."""
    words = [
        " ".join(str(event.get(k) or "").split()) for k in ("summary", "location", "description")
    ]
    parts = [words[0], _epoch(event.get("start")), _epoch(event.get("end")), *words[1:]]
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:16]


def _private(event: Mapping[str, Any]) -> Mapping[str, Any]:
    props = event.get("extendedProperties")
    private = props.get("private") if isinstance(props, Mapping) else None
    return private if isinstance(private, Mapping) else {}


def number_of(event: Mapping[str, Any], batch: str) -> int | None:
    mark = str(_private(event).get(BATCH_KEY) or "")
    head, _, n = mark.rpartition(":")
    return int(n) if head == batch and n.isdigit() else None


def changed_by_owner(event: Mapping[str, Any]) -> bool:
    """The event no longer reads as JARVIS wrote it (D5: an Undo leaves it alone)."""
    return _private(event).get(SIG_KEY) != signature(event)


def stamped(
    body: Mapping[str, Any], batch: str, n: int, current: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """`body` with the batch's markers (and every private property `current` already has)."""
    old = current.get("extendedProperties") if isinstance(current, Mapping) else None
    props = dict(old) if isinstance(old, Mapping) else {}
    seen = {**(current or {}), **body}
    private = {
        **_private(current or {}),
        **_private(body),
        BATCH_KEY: f"{batch}:{n}",
        BATCH_ID_KEY: batch,
        SIG_KEY: signature(seen),
    }
    return {**body, "extendedProperties": {**props, "private": private}}


def same_events(
    items: Sequence[Wanted],
    have: Mapping[int, Mapping[str, Any]],
    sig_of: Callable[[Wanted], str],
) -> dict[int, int]:
    """Continuing a batch: an item without `n` that is an event the batch already holds (the
    title, times, place and notes JARVIS wrote: `signature`) keeps that event's number, so a
    whole list sent again adds nothing twice. Position in `items` -> number."""
    taken = {w.n for w in items if w.n is not None}
    waiting: dict[str, list[int]] = {}
    for n in sorted(have):
        sig = str(_private(have[n]).get(SIG_KEY) or "")
        if sig and n not in taken:
            waiting.setdefault(sig, []).append(n)
    out: dict[int, int] = {}
    for i, w in enumerate(items):
        if w.n is None and (free := waiting.get(sig_of(w))):
            out[i] = free.pop(0)
    return out


def numbered(
    items: Sequence[Wanted],
    have: Collection[int],
    continuing: bool,
    same: Mapping[int, int] | None = None,
) -> list[tuple[int, Wanted]]:
    """Each item's number in the batch: its own `n`; the number of the event it already is
    (`same`, from `same_events`); else its position, or (continuing an earlier batch) the next
    free number, so a retried item never takes another's place."""
    out: list[tuple[int, Wanted]] = []
    known = dict(same or {})
    used = {w.n for w in items if w.n is not None} | set(known.values())
    used |= set(have) if continuing else set()
    free = 1
    for i, w in enumerate(items, 1):
        own = w.n if w.n is not None else known.get(i - 1)
        if own is not None:
            out.append((own, w))
            continue
        if not continuing and i not in used:
            n = i
        else:
            while free in used:
                free += 1
            n = free
        used.add(n)
        out.append((n, w))
    return out


# ---- many single calls -> one batch (O2) ---------------------------------------------------------

Spread = Callable[[list[GatewayResult]], list[GatewayResult]]


def gathered(
    calls: Sequence[ToolCall], registry: ToolRegistry, limit: int
) -> tuple[list[ToolCall], Spread]:
    """One round's calls as the gateway should see them, and how to give every original call its
    result back. More than `MANY` valid single creates without guests become one batch call per
    `limit` events, in place of the first of them; the others are answered `MERGED`."""
    single, batch = registry.get(SINGLE), registry.get(CREATE)
    mergeable = [i for i, c in enumerate(calls) if _mergeable(c, single)]
    if single is None or batch is None or len(mergeable) <= MANY:
        return list(calls), lambda out: out
    heads: dict[int, ToolCall] = {}
    for at in range(0, len(mergeable), limit):
        part = mergeable[at : at + limit]
        events = [dict(calls[i].arguments) for i in part]
        heads[part[0]] = ToolCall(id=calls[part[0]].id, name=CREATE, arguments={"events": events})
    merged = set(mergeable) - set(heads)
    run = [heads.get(i, c) for i, c in enumerate(calls) if i not in merged]

    def spread(out: list[GatewayResult]) -> list[GatewayResult]:
        results = iter(out)
        note = GatewayResult(GatewayOutcome.DENIED, error=MERGED)
        return [note if i in merged else next(results) for i in range(len(calls))]

    log.info("single creates gathered into a batch", extra={"events": len(mergeable)})
    return run, spread


def _mergeable(call: ToolCall, single: Tool | None) -> bool:
    if single is None or call.name != SINGLE or call.arguments.get("attendees"):
        return False
    try:
        single.validate(call.arguments)
    except ValueError:
        return False
    return True


__all__ = [
    "BATCH_ID",
    "BATCH_ID_KEY",
    "BATCH_KEY",
    "CREATE",
    "GUESTS",
    "MANY",
    "MERGED",
    "SIG_KEY",
    "SINGLE",
    "UNDO",
    "Batch",
    "Made",
    "Outcome",
    "PlanBook",
    "Wanted",
    "batch_id",
    "changed_by_owner",
    "gathered",
    "number_of",
    "numbered",
    "parse",
    "same_events",
    "signature",
    "stamped",
    "title_of",
]
