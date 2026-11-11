# src/jarvis/helpers/house/feed.py
"""NDMA SACHET's RSS feed and its queue's bookkeeping (docs/plans/r11-free-helpers.md D13; the
reviews' M2, H2, M5 and L4). Pure: no I/O.

- `parse_rss`: the state's RSS through the same two-layer XML reader as a CAP (`xmlsafe`); only
  digits-only guids (an item's own link is never followed: the CAP URL is built from the guid).
- `safe_etag`: an ETag is kept only when it is printable ASCII of at most 200 characters, so the
  `If-None-Match` JARVIS sends back can always be built (security review M2).
- `queue_items`: each new guid queued once (items naming his district in their title first); an
  item older than a day is just marked seen.
- `waiting`, `failed`, `aged`, `settle`: a CAP whose URL refused (non-200) backs off (5 minutes,
  doubling, at most an hour) and the queue goes on past it; it ages out (seen, never fetched
  again) after `MAX_CAP_FAILS` refusals or once it has been failing for `MAX_CAP_AGE`. A run that
  read no CAP but failed to keeps `cap_fail_since` (an outage, shown); one that read a CAP clears
  it (code review H2, M5).
- `live`: the warnings still in force: before their `expires`, or for `NO_EXPIRY` (a day) after
  JARVIS heard of one that has none (security review L4).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

from jarvis.helpers.house.cap import norm
from jarvis.helpers.house.models import (
    MAX_QUEUE,
    MAX_SEEN,
    Backoff,
    Place,
    SachetState,
    Warning,
    clean_text,
)
from jarvis.helpers.house.xmlsafe import parse_xml
from jarvis.helpers.sources import MAX_RSS_BYTES

MAX_ITEMS = 300
STALE_ITEM = timedelta(hours=24)
MAX_CAP_FAILS = 5
MAX_CAP_AGE = timedelta(hours=24)
BACKOFF_FIRST = timedelta(minutes=5)
BACKOFF_MAX = timedelta(hours=1)
NO_EXPIRY = timedelta(hours=24)
ETAG_MAX = 200
_GUID = re.compile(r"^\d{6,30}$")


@dataclass(frozen=True)
class Item:
    guid: str
    category: str
    title: str  # outside text: used only to order the queue, never shown or sent
    published: datetime | None


def iso(at: datetime) -> str:
    return at.isoformat()


def _published(value: str) -> datetime | None:
    try:
        got = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    return got if got.tzinfo is not None else None


def parse_rss(raw: bytes) -> tuple[Item, ...]:
    root = parse_xml(raw, limit=MAX_RSS_BYTES)
    channel = root.find("channel") if root.tag == "rss" else None
    if channel is None:
        raise ValueError("Not an RSS feed.")
    out = []
    for el in channel.findall("item")[:MAX_ITEMS]:
        guid = clean_text(el.findtext("guid") or "", 40)
        if _GUID.match(guid):
            out.append(
                Item(
                    guid=guid,
                    category=clean_text(el.findtext("category") or "", 20),
                    title=clean_text(el.findtext("title") or "", 200),
                    published=_published(clean_text(el.findtext("pubDate") or "", 60)),
                )
            )
    return tuple(out)


def safe_etag(value: str | None) -> str | None:
    if not value or len(value) > ETAG_MAX or not all(" " <= c <= "~" for c in value):
        return None
    return value


def queue_items(
    state: SachetState, items: Sequence[Item], place: Place, now: datetime
) -> SachetState:
    known = set(state.seen) | set(state.queue)
    new = [i for i in items if i.guid not in known]
    stale = [i.guid for i in new if i.published is not None and now - i.published > STALE_ITEM]
    district = f" {norm(place.district)} "
    fresh = sorted(
        (i for i in new if i.guid not in stale),
        key=lambda i: 0 if district in f" {norm(i.title)} " else 1,
    )
    return state.model_copy(
        update={
            "queue": (*(i.guid for i in fresh), *state.queue)[:MAX_QUEUE],
            "seen": (*stale, *state.seen)[:MAX_SEEN],
        }
    )


def _backoff(state: SachetState, guid: str) -> Backoff | None:
    return next((b for b in state.backoff if b.guid == guid), None)


def waiting(state: SachetState, guid: str, now: datetime) -> bool:
    b = _backoff(state, guid)
    return b is not None and now < datetime.fromisoformat(b.next_at)


def aged(state: SachetState, guid: str, now: datetime) -> bool:
    b = _backoff(state, guid)
    return b is not None and (
        b.fails >= MAX_CAP_FAILS or now - datetime.fromisoformat(b.since) >= MAX_CAP_AGE
    )


def failed(state: SachetState, guid: str, now: datetime) -> SachetState:
    """One more refusal of this guid's CAP: its next try backs off."""
    b = _backoff(state, guid)
    fails = (b.fails if b else 0) + 1
    wait = min(BACKOFF_FIRST * 2 ** (fails - 1), BACKOFF_MAX)
    new = Backoff(guid=guid, since=b.since if b else iso(now), fails=fails, next_at=iso(now + wait))
    rest = tuple(x for x in state.backoff if x.guid != guid)
    return state.model_copy(update={"backoff": (new, *rest)[:MAX_QUEUE]})


def settle(
    state: SachetState, done: Sequence[str], now: datetime, *, read: bool, failing: bool
) -> SachetState:
    """The run's end: done guids seen, out of the queue and the backoff; the CAP outage kept or
    cleared."""
    gone = set(done)
    if read:
        outage = None
    else:
        outage = (state.cap_fail_since or iso(now)) if failing else state.cap_fail_since
    return state.model_copy(
        update={
            "queue": tuple(g for g in state.queue if g not in gone),
            "seen": (*done, *state.seen)[:MAX_SEEN],
            "backoff": tuple(b for b in state.backoff if b.guid not in gone),
            "cap_fail_since": outage,
        }
    )


def _in_force(w: Warning, now: datetime) -> bool:
    if w.until is not None:
        return datetime.fromisoformat(w.until) > now
    return now - datetime.fromisoformat(w.at) < NO_EXPIRY


def live(warnings: Sequence[Warning], now: datetime) -> tuple[Warning, ...]:
    return tuple(w for w in warnings if _in_force(w, now))


def live_state(state: SachetState, now: datetime) -> SachetState:
    keep = live(state.warnings, now)
    return state.model_copy(update={"warnings": keep}) if keep != state.warnings else state


__all__ = [
    "MAX_CAP_AGE",
    "MAX_CAP_FAILS",
    "NO_EXPIRY",
    "STALE_ITEM",
    "Backoff",
    "Item",
    "aged",
    "failed",
    "iso",
    "live",
    "live_state",
    "parse_rss",
    "queue_items",
    "safe_etag",
    "settle",
    "waiting",
]
