# src/jarvis/helpers/house/sachet.py
"""Item 5, disaster alerts for India from NDMA SACHET (docs/plans/r11-free-helpers.md D13).

`DisasterJob` (`disaster_poll`, the 5-minute clock), for each configured owner with a place whose
"Weather and alerts" row isn't Never, inside SACHET's own slot of Part B's share of the run
(`fetch.OutsideClock`; weather has its own, so neither starves the other):
- every `disaster_poll_minutes` (10) it reads his state's RSS feed (`rss_kerala.xml`; the
  national `rss_india.xml` for a state without one) with `If-None-Match` when it holds a safe
  ETag (`feed.safe_etag`); a request JARVIS can't build clears the ETag and is retried without it
  next run, never counted as SACHET's outage. New digits-only guids are queued (`feed`).
- every run, while the queue isn't empty: up to `MAX_CAPS_PER_RUN` CAP messages, each fetched
  with what is left of the slot. A CAP that refuses (non-200) backs off and the queue goes on
  past it; it ages out after a bounded number of refusals or a day. A host that doesn't answer
  ends the run's CAP reads and is kept as an outage until a CAP is read (`cap_fail_since`).
- each CAP (`cap.parse_cap`; refused when unsafe, then never fetched again): Actual and Public
  only; a Cancel of a warning told before says "lifted" (`weather_note`, with or without an info
  block); otherwise his district only (`cap.matches_place`), not expired; D13's kind; an Update
  of a warning already told rings again only when it got worse; a series of IMD nowcasts (same
  event word and kind within 3 hours) is told once.
- telling (`night.CapTeller`): leased claims per CAP identifier and per content key, and at night
  at most three urgent rings, then one held morning summary and one "more" ring an hour. Its
  text is a fixed template from a fixed event word, his own district and the expiry: "Urgent:
  Landslide warning for Ernakulam until 18:00 (SACHET). Open JARVIS." The CAP's own words are
  kept, sealed, only for the panel; a warning without an expiry lapses after a day.
- the official SACHET app, SMS and cell broadcast stay the primary channel.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from jarvis.helpers.house import cap as cap_mod
from jarvis.helpers.house import feed, words
from jarvis.helpers.house.cap import RANK, Alert, Info, UnsafeXml
from jarvis.helpers.house.feed import Item, iso, parse_rss
from jarvis.helpers.house.fetch import (
    MIN_LEFT_S,
    SACHET_SLOT_S,
    BadRequest,
    Fetcher,
    FetchError,
    OutsideClock,
    TooLarge,
)
from jarvis.helpers.house.guard import Counts, allowed
from jarvis.helpers.house.models import MAX_WARNINGS, Outside, Place, SachetState, Warning
from jarvis.helpers.house.night import CapMessage, CapTeller, content_key
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
BUDGET_S = SACHET_SLOT_S + 1.0
MAX_CAPS_PER_RUN = 6
RETRY_AFTER = timedelta(minutes=5)
NOWCAST_QUIET = timedelta(hours=3)
_KINDS = ("Alert", "Update", "Cancel")
_COUNTS = ("sent", "retry", "unreachable", "refused", "cap_refused", "aged", "local_error")


def _due(state: SachetState, now: datetime) -> bool:
    return state.next_at is None or now >= datetime.fromisoformat(state.next_at)


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
        clock: OutsideClock | None = None,
    ) -> None:
        self._ctx = ctx
        self._outside = outside
        self._fetcher = fetcher
        self._clock = clock or OutsideClock()
        self._teller = CapTeller(ctx, store)
        self._every = timedelta(minutes=ctx.settings.disaster_poll_minutes)

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        """`owners` is ignored: the helpers serve the configured owners (`ctx.owners`)."""
        n = Counts()
        deadline = self._clock.deadline("sachet")
        for uid in self._ctx.owners:
            try:
                if not await allowed(self._ctx, uid, "disaster_status"):
                    n.add("skipped")
                    continue
                await self._owner(uid, n, deadline)
            except OutsideOff:
                n.add("off")
            except Exception as exc:  # noqa: BLE001 - one owner never blocks another
                log.warning("SACHET job failed for an owner", extra={"error": type(exc).__name__})
                n.add("failed")
        return n.done(*_COUNTS, "skipped", "failed")

    async def _owner(self, uid: str, n: Counts, deadline: float) -> None:
        o = await self._outside.read(uid)
        if o.place is None:
            n.add("no_place")
            return
        now = self._ctx.now()
        feed_name = o.place.feed()
        state = o.sachet if o.sachet.feed == feed_name else SachetState(feed=feed_name)
        state = feed.live_state(state, now)
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
        left = self._clock.left(deadline)
        if left < MIN_LEFT_S:
            return state  # SACHET's slot is spent (another owner): the next run
        headers = {"If-None-Match": state.etag} if state.etag else {}
        try:
            got = await self._fetcher.get(
                SACHET_RSS_URL.format(feed=state.feed or place.feed()),
                headers=headers,
                cap=MAX_RSS_BYTES,
                timeout_s=min(OUTSIDE_TIMEOUT_S, left),
            )
            items = () if got.status == 304 else parse_rss(got.body)
        except BadRequest:
            n.add("local_error")  # JARVIS's own request: no ETag next run, not an outage
            return state.model_copy(update={"etag": None, "next_at": iso(now)})
        except (FetchError, ValueError) as exc:
            log.warning("SACHET feed unreachable", extra={"error": type(exc).__name__})
            n.add("unreachable")
            refused = isinstance(exc, FetchError) and exc.status is not None
            return state.model_copy(
                update={
                    "checked_at": iso(now),
                    "next_at": iso(now + RETRY_AFTER),
                    "fail_since": state.fail_since or iso(now),
                    "etag": None if refused else state.etag,
                }
            )
        return feed.queue_items(self._fed(state, got.status, got.etag, now), items, place, now)

    def _fed(self, state: SachetState, status: int, etag: str | None, now: datetime) -> SachetState:
        kept = state.etag if status == 304 and not etag else feed.safe_etag(etag)
        return state.model_copy(
            update={
                "checked_at": iso(now),
                "next_at": iso(now + self._every),
                "ok_at": iso(now),
                "fail_since": None,
                "etag": kept,
            }
        )

    async def _work(
        self, uid: str, place: Place, state: SachetState, now: datetime, deadline: float, n: Counts
    ) -> SachetState:
        done: list[str] = []
        read = failing = False
        tried = 0
        for guid in tuple(state.queue):
            if feed.aged(state, guid, now):
                n.add("aged")
                done.append(guid)
                continue
            left = self._clock.left(deadline)
            if tried >= MAX_CAPS_PER_RUN or left < MIN_LEFT_S:
                break
            if feed.waiting(state, guid, now):
                continue
            tried += 1
            try:
                alert = await self._read_cap(guid, left)
            except (TooLarge, ValueError) as exc:  # UnsafeXml is a ValueError: refused for good
                log.warning("a SACHET CAP was refused", extra={"error": type(exc).__name__})
                n.add("refused")
                read = True
                done.append(guid)
                continue
            except FetchError as exc:
                failing = True
                if isinstance(exc, BadRequest) or exc.status is None:
                    n.add("unreachable")  # the host, not this CAP: the rest waits
                    break
                n.add("cap_refused")
                state = feed.failed(state, guid, now)
                if feed.aged(state, guid, now):
                    n.add("aged")
                    done.append(guid)
                continue
            read = True
            state, keep = await self._consider(uid, place, state, alert, now, n)
            if not keep:
                done.append(guid)
        return feed.settle(state, done, now, read=read, failing=failing)

    async def _read_cap(self, guid: str, left: float) -> Alert:
        got = await self._fetcher.get(
            SACHET_CAP_URL,
            params={"identifier": guid},
            cap=MAX_CAP_BYTES,
            timeout_s=min(OUTSIDE_TIMEOUT_S, left),
        )
        return cap_mod.parse_cap(got.body)

    async def _consider(
        self, uid: str, place: Place, state: SachetState, alert: Alert, now: datetime, n: Counts
    ) -> tuple[SachetState, bool]:
        """(the new state, keep the item queued: its send must be tried again)."""
        if alert.status != "Actual" or alert.scope != "Public" or alert.msg_type not in _KINDS:
            n.add("ignored")
            return state, False
        refs = alert.references
        earlier = next((w for w in state.warnings if w.ident in refs or w.root in refs), None)
        if alert.msg_type == "Cancel":  # its info block is optional (CAP 1.2, code review L2)
            return await self._lift(uid, place, state, alert, earlier, now, n)
        info = alert.info
        if info is None or not cap_mod.matches_place(info, place):
            n.add("ignored" if info is None else "elsewhere")
            return state, False
        if info.expires is not None and info.expires <= now:
            n.add("expired")
            return state, False
        return await self._tell(uid, place, state, alert, info, earlier, now, n)

    @staticmethod
    def _quiet(
        state: SachetState, kind: str, event: str, earlier: Warning | None, now: datetime
    ) -> bool:
        """Told already: an Update that didn't get worse, or a nowcast of a series."""
        if earlier is not None and RANK[kind] <= RANK[earlier.kind]:
            return True
        return kind != "disaster_alert" and any(
            w.event == event
            and w.kind == kind
            and now - datetime.fromisoformat(w.at) < NOWCAST_QUIET
            for w in state.warnings
        )

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
        onset = local(info.onset or alert.sent or now, self._ctx.tz).date().isoformat()
        key = content_key(kind, event, place.district, onset)
        warning = Warning(
            ident=alert.identifier,
            root=root,
            kind=kind,
            event=event,
            until=iso(info.expires) if info.expires else None,
            at=iso(now),
            headline=info.headline,
            instruction=info.instruction,
            key=key,
        )
        if not self._quiet(state, kind, event, earlier, now):
            here = local(now, self._ctx.tz)
            ends = words.until(local(info.expires, self._ctx.tz) if info.expires else None, here)
            subject = f"cap:{claim_key(uid, 'cap', root)[:16]}"
            m = CapMessage(
                alert.identifier, kind, words.cap(kind, event, place.district, ends), subject,
                key, place.district,
            )  # fmt: skip
            if not await self._teller.tell(uid, m, now, n):
                return state, True
        rest = tuple(w for w in state.warnings if w.root != root and w.key != key)
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
        if not await self._teller.plain(uid, alert.identifier, "weather_note", text, now, n):
            return state, True
        rest = tuple(w for w in state.warnings if w.root != earlier.root)
        return state.model_copy(update={"warnings": rest}), False


__all__ = ["JOB", "MAX_CAPS_PER_RUN", "DisasterJob", "Item", "UnsafeXml", "parse_rss"]
