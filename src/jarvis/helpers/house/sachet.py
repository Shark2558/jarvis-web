# src/jarvis/helpers/house/sachet.py
"""Item 5, disaster alerts for India from NDMA SACHET (docs/plans/r11-free-helpers.md D13).

`DisasterJob` (`disaster_poll`, the 5-minute clock), for each configured owner with a place whose
"Weather and alerts" row isn't Never:
- every `disaster_poll_minutes` (10) it reads his state's RSS feed (`rss_kerala.xml`; the
  national `rss_india.xml` for a state without one), with `If-None-Match` (SACHET asks consumers
  to use ETags). Each item's digits-only guid is queued once; an item older than a day is just
  marked seen. The item's own link is never followed: the CAP URL is built from the guid.
- every run, while the queue isn't empty: up to `MAX_CAPS_PER_RUN` CAP messages (8 s each,
  inside the job's own soft deadline), items naming his district in their title first.
- each CAP (`cap.parse_cap`; refused when unsafe, then never fetched again): Actual and Public
  only, his district only (`cap.matches_place`), not expired; D13's kind; an Update of a warning
  already told rings again only when it got worse; a series of IMD nowcasts (same event word and
  kind within 3 hours) is told once; a Cancel tells "lifted" (`weather_note`).
- an alert is claimed by its CAP identifier (`house_told`) before it goes, and released (the
  item stays queued) when no channel took it. Its text is a fixed template from a fixed event word,
  his own district and the expiry: "Urgent: Landslide warning for Ernakulam until 18:00 (SACHET).
  Open JARVIS." The CAP's own words are kept, sealed, only for the panel.
- the feed's outage is kept ("can't reach SACHET since ..."); the official SACHET app, SMS and
  cell broadcast stay the primary channel.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

from jarvis.alerts import AlertKind
from jarvis.helpers.house import cap as cap_mod
from jarvis.helpers.house import words
from jarvis.helpers.house.cap import Alert, Info, UnsafeXml, parse_xml
from jarvis.helpers.house.fetch import Fetcher, FetchError, TooLarge
from jarvis.helpers.house.guard import Counts, allowed
from jarvis.helpers.house.models import (
    MAX_QUEUE,
    MAX_SEEN,
    MAX_WARNINGS,
    Outside,
    Place,
    SachetState,
    Warning,
    clean_text,
)
from jarvis.helpers.house.store import HouseStore, OutsideOff, OutsideStore, claim_key
from jarvis.helpers.ports import HelperContext
from jarvis.helpers.sources import (
    MAX_CAP_BYTES,
    MAX_RSS_BYTES,
    OUTSIDE_TIMEOUT_S,
    SACHET_CAP_URL,
    SACHET_RSS_URL,
)
from jarvis.logging import get_logger
from jarvis.notify.quiet import local

log = get_logger(__name__)

JOB = "disaster_poll"
BUDGET_S = 10.0
SOFT_S = 9.0  # the job's own deadline, inside its budget
MIN_LEFT_S = 1.0
MAX_CAPS_PER_RUN = 6
MAX_ITEMS = 300
STALE_ITEM = timedelta(hours=24)
RETRY_AFTER = timedelta(minutes=5)
NOWCAST_QUIET = timedelta(hours=3)
RANK = {"weather_note": 0, "weather_warning": 1, "disaster_alert": 2}
_GUID = re.compile(r"^\d{6,30}$")


@dataclass(frozen=True)
class Item:
    guid: str
    category: str
    title: str  # outside text: used only to order the queue, never shown or sent
    published: datetime | None


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


def _iso(at: datetime) -> str:
    return at.isoformat()


def _due(state: SachetState, now: datetime) -> bool:
    return state.next_at is None or now >= datetime.fromisoformat(state.next_at)


def _live(state: SachetState, now: datetime) -> SachetState:
    keep = tuple(
        w for w in state.warnings if w.until is None or datetime.fromisoformat(w.until) > now
    )
    return state.model_copy(update={"warnings": keep}) if keep != state.warnings else state


def _queue(state: SachetState, items: Sequence[Item], place: Place, now: datetime) -> SachetState:
    known = set(state.seen) | set(state.queue)
    new = [i for i in items if i.guid not in known]
    stale = [i.guid for i in new if i.published is not None and now - i.published > STALE_ITEM]
    district = f" {cap_mod.norm(place.district)} "
    fresh = sorted(
        (i for i in new if i.guid not in stale),
        key=lambda i: 0 if district in f" {cap_mod.norm(i.title)} " else 1,
    )
    return state.model_copy(
        update={
            "queue": (*(i.guid for i in fresh), *state.queue)[:MAX_QUEUE],
            "seen": (*stale, *state.seen)[:MAX_SEEN],
        }
    )


class DisasterJob:
    name = JOB
    budget_s = BUDGET_S

    def __init__(
        self,
        ctx: HelperContext,
        outside: OutsideStore,
        store: HouseStore,
        fetcher: Fetcher,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ctx = ctx
        self._outside = outside
        self._store = store
        self._fetcher = fetcher
        self._clock = clock
        self._every = timedelta(minutes=ctx.settings.disaster_poll_minutes)

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        """`owners` is ignored: the helpers serve the configured owners (`ctx.owners`)."""
        n = Counts()
        for uid in self._ctx.owners:
            try:
                if not await allowed(self._ctx, uid, "disaster_status"):
                    n.add("skipped")
                    continue
                await self._owner(uid, n)
            except OutsideOff:
                n.add("off")
            except Exception as exc:  # noqa: BLE001 - one owner never blocks another
                log.warning("SACHET job failed for an owner", extra={"error": type(exc).__name__})
                n.add("failed")
        return n.done("sent", "retry", "unreachable", "refused", "skipped", "failed")

    def _left(self, deadline: float) -> float:
        return deadline - self._clock()

    async def _owner(self, uid: str, n: Counts) -> None:
        o = await self._outside.read(uid)
        if o.place is None:
            n.add("no_place")
            return
        now, deadline = self._ctx.now(), self._clock() + SOFT_S
        feed = o.place.feed()
        state = o.sachet if o.sachet.feed == feed else SachetState(feed=feed)
        state = _live(state, now)
        if _due(state, now):
            state = await self._read_feed(state, o.place, now, deadline, n)
        if state.queue:
            state = await self._work(uid, o.place, state, now, deadline, n)
        if state != o.sachet:
            await self._save(uid, o.place, state)

    async def _save(self, uid: str, place: Place, state: SachetState) -> None:
        def apply(cur: Outside) -> Outside:
            if cur.place != place:
                return cur  # his place changed meanwhile: this state is for the old one
            return cur.model_copy(update={"sachet": state})

        await self._outside.change(uid, apply)

    async def _read_feed(
        self, state: SachetState, place: Place, now: datetime, deadline: float, n: Counts
    ) -> SachetState:
        headers = {"If-None-Match": state.etag} if state.etag else {}
        stamp = {"checked_at": _iso(now)}
        try:
            got = await self._fetcher.get(
                SACHET_RSS_URL.format(feed=state.feed or place.feed()),
                headers=headers,
                cap=MAX_RSS_BYTES,
                timeout_s=min(OUTSIDE_TIMEOUT_S, self._left(deadline)),
            )
            items = () if got.status == 304 else parse_rss(got.body)
        except (FetchError, ValueError) as exc:
            log.warning("SACHET feed unreachable", extra={"error": type(exc).__name__})
            n.add("unreachable")
            return state.model_copy(
                update={
                    **stamp,
                    "next_at": _iso(now + RETRY_AFTER),
                    "fail_since": state.fail_since or _iso(now),
                }
            )
        ok = state.model_copy(
            update={
                **stamp,
                "next_at": _iso(now + self._every),
                "ok_at": _iso(now),
                "fail_since": None,
                "etag": clean_text(got.etag or "", 200) or None,
            }
        )
        return _queue(ok, items, place, now)

    async def _work(
        self, uid: str, place: Place, state: SachetState, now: datetime, deadline: float, n: Counts
    ) -> SachetState:
        done: list[str] = []
        for guid in state.queue[:MAX_CAPS_PER_RUN]:
            left = self._left(deadline)
            if left < MIN_LEFT_S:
                break
            try:
                got = await self._fetcher.get(
                    SACHET_CAP_URL,
                    params={"identifier": guid},
                    cap=MAX_CAP_BYTES,
                    timeout_s=min(OUTSIDE_TIMEOUT_S, left),
                )
                alert = cap_mod.parse_cap(got.body)
            except (TooLarge, ValueError) as exc:  # UnsafeXml is a ValueError: refused for good
                log.warning("a SACHET CAP was refused", extra={"error": type(exc).__name__})
                n.add("refused")
                done.append(guid)
                continue
            except FetchError as exc:
                log.warning("a SACHET CAP unreachable", extra={"error": type(exc).__name__})
                n.add("unreachable")
                break
            state, keep = await self._consider(uid, place, state, alert, now, n)
            if not keep:
                done.append(guid)
        gone = set(done)
        return state.model_copy(
            update={
                "queue": tuple(g for g in state.queue if g not in gone),
                "seen": (*done, *state.seen)[:MAX_SEEN],
            }
        )

    async def _consider(
        self, uid: str, place: Place, state: SachetState, alert: Alert, now: datetime, n: Counts
    ) -> tuple[SachetState, bool]:
        """(the new state, keep the item queued: its send must be tried again)."""
        info = alert.info
        if (
            info is None
            or alert.status != "Actual"
            or alert.scope != "Public"
            or alert.msg_type not in ("Alert", "Update", "Cancel")
        ):
            n.add("ignored")
            return state, False
        if not cap_mod.matches_place(info, place):
            n.add("elsewhere")
            return state, False
        earlier = next(
            (
                w
                for w in state.warnings
                if w.ident in alert.references or w.root in alert.references
            ),
            None,
        )
        if alert.msg_type == "Cancel":
            return await self._lift(uid, place, state, alert, earlier, now, n)
        if info.expires is not None and info.expires <= now:
            n.add("expired")
            return state, False
        return await self._tell(uid, place, state, alert, info, earlier, now, n)

    async def _tell(
        self,
        uid: str,
        place: Place,
        state: SachetState,
        alert: Alert,
        info: Info,
        earlier: Warning | None,
        now: datetime,
        n: Counts,
    ) -> tuple[SachetState, bool]:
        kind = cap_mod.kind_for(info)
        event = words.event_word(info.event, kind)
        root = earlier.root if earlier is not None else alert.identifier
        quiet = (earlier is not None and RANK[kind] <= RANK[earlier.kind]) or any(
            w.event == event
            and w.kind == kind
            and kind != "disaster_alert"
            and now - datetime.fromisoformat(w.at) < NOWCAST_QUIET
            for w in state.warnings
        )
        warning = Warning(
            ident=alert.identifier,
            root=root,
            kind=kind,
            event=event,
            until=_iso(info.expires) if info.expires else None,
            at=_iso(now),
            headline=info.headline,
            instruction=info.instruction,
        )
        if not quiet:
            here = local(now, self._ctx.tz)
            ends = words.until(local(info.expires, self._ctx.tz) if info.expires else None, here)
            text = words.cap(kind, event, place.district, ends)
            subject = f"cap:{claim_key(uid, 'cap', root)[:16]}"
            if not await self._send(uid, kind, alert.identifier, text, subject, now, n):
                return state, True
        rest = tuple(w for w in state.warnings if w.root != root)
        return state.model_copy(update={"warnings": (warning, *rest)[:MAX_WARNINGS]}), False

    async def _lift(
        self,
        uid: str,
        place: Place,
        state: SachetState,
        alert: Alert,
        earlier: Warning | None,
        now: datetime,
        n: Counts,
    ) -> tuple[SachetState, bool]:
        if earlier is None:
            n.add("ignored")
            return state, False
        text = words.lifted(earlier.event, place.district)
        if not await self._send(uid, "weather_note", alert.identifier, text, None, now, n):
            return state, True
        rest = tuple(w for w in state.warnings if w.root != earlier.root)
        return state.model_copy(update={"warnings": rest}), False

    async def _send(
        self,
        uid: str,
        kind: AlertKind,
        ident: str,
        text: str,
        subject: str | None,
        now: datetime,
        n: Counts,
    ) -> bool:
        """Claim, send, release on retry. False: try again next run."""
        if not await self._store.claim(uid, "cap", ident, now):
            return True  # told before (a restart, or the same CAP again)
        got = await self._ctx.sender.send(uid, kind, text, due=now, subject=subject)
        if got.retry:
            await self._store.release(uid, "cap", ident)
            n.add("retry")
            return False
        n.add("sent" if got.counted else "dropped")
        return True


__all__ = ["JOB", "MAX_CAPS_PER_RUN", "DisasterJob", "Item", "UnsafeXml", "parse_rss"]
