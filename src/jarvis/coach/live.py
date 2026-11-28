# src/jarvis/coach/live.py
"""R8 (docs/plans/r8-vision.md v8.0.4 section 4.5a; the owner's D3, D6, D11, D12; seam S24's cloud
half; builder J): the home laptop's coach reports in the cloud, and the coach part of the state
the cloud sends the bridge. Cloud only. Implements the `HomeVision` port (`jarvis.coach.ports`),
a `HomeEventHandler` for "coach" events and a `StateSource` (`jarvis.home.ports`).

- **Views** (`live(uid, use)`, for `GET /v1/coach/live`): the newest view of each body the laptop
  reported for a use case, kept in memory only for `LIVE_TTL_S` (at most `BODIES_MAX` bodies a
  use case, the oldest dropped). Never stored, never logged.
- **Tallies** (D6 final, D12): a report's tally is kept through `CoachStore.keep` when it fits its
  use case's model (`usecases.parse_tally`; dropped, never repaired), its use case runs on a home
  camera, it was switched on for that camera and "cameras off" isn't set (when the cloud knows the
  switches). A body the laptop didn't know (`who` "") is kept as its session's guest ("Guest N",
  `PeopleStore.guest_for`). A store that is down raises, so the webhook gives the event back and
  the bridge retries; a tally that can't be kept (no keyring, a full day) is dropped with its class
  in the log.
- **The coach part** (`push`, `state_part`): which use cases run on which home camera, the
  tracking target and "cameras off". `push` sends it at once (`POST /bridge/v1/state`; an offline
  laptop catches up from the next heartbeat reply); `state_part` gives it with every heartbeat
  reply, read from `reader` (I1: B's switches and the target store, the durable truth) or the last
  push. Its `rev` grows whenever the content changes (centiseconds since 1970, never lower than the
  last), so after a cloud restart the same content is sent again with a newer rev, which the
  bridge applies harmlessly. It never carries the alarm's arm state (D11).
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from jarvis.coach.people import CoachOff, PeopleRefused, PeopleStore
from jarvis.coach.store import CoachStore, DayFull, Dropped
from jarvis.coach.target import TrackTarget
from jarvis.coach.usecases import BY_ID, parse_tally
from jarvis.home.ports import (
    MAX_REV,
    BridgeState,
    CoachReport,
    CoachState,
    HomeCaller,
    HomeUnavailable,
)
from jarvis.logging import get_logger

log = get_logger(__name__)

LIVE_TTL_S = 120.0
BODIES_MAX = 4
STATE_PATH = "/bridge/v1/state"


@dataclass(frozen=True)
class Wanted:
    """What the owner switched on for the home cameras (the content of the coach part)."""

    uses: tuple[tuple[str, tuple[str, ...]], ...] = ()
    target: str = "all"
    person: str | None = None
    all_off: bool = False

    @classmethod
    def of(cls, uses: Mapping[str, Sequence[str]], target: TrackTarget, all_off: bool) -> Wanted:
        return cls(
            tuple(
                sorted((str(c), tuple(dict.fromkeys(str(u) for u in us))) for c, us in uses.items())
            ),  # fmt: skip
            target.kind,
            target.person,
            bool(all_off),
        )

    def on(self, camera: str, use: str) -> bool:
        return not self.all_off and use in dict(self.uses).get(camera, ())


Reader = Callable[[str], Awaitable[Wanted | None]]


@dataclass(frozen=True)
class _Sent:
    wanted: Wanted
    rev: int


class HomeLive:
    handles = frozenset({"coach"})

    def __init__(
        self,
        store: CoachStore | None,
        people: PeopleStore | None,
        *,
        caller: HomeCaller | None = None,
        reader: Reader | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._people = people
        self._caller = caller
        self._reader = reader
        self._clock = clock
        self._views: dict[tuple[str, str], dict[int, dict[str, Any]]] = {}
        self._sent: dict[str, _Sent] = {}

    # ---- the laptop's reports ------------------------------------------------------------------

    async def handle(self, uid: str, event: Any) -> None:
        if not isinstance(event, CoachReport):
            return
        use = BY_ID.get(event.use)
        if use is None or use.source != "home":
            log.info("a coach report for a use case that is not a home one was ignored")
            return
        wanted = await self._wanted(uid)
        if wanted is not None and not wanted.on(event.camera, event.use):
            log.info("a coach report for a coach that is off was ignored")
            return
        self._remember(uid, event)
        if event.tally is not None:
            await self._keep(uid, event)

    def _remember(self, uid: str, event: CoachReport) -> None:
        bodies = self._views.setdefault((uid, event.use), {})
        bodies[event.track] = {
            "track": event.track,
            "who": event.who,
            "camera": event.camera,
            "at": event.at,
            "view": [dict(w) for w in event.view],
        }
        while len(bodies) > BODIES_MAX:
            del bodies[min(bodies, key=lambda t: bodies[t]["at"])]

    async def _keep(self, uid: str, event: CoachReport) -> None:
        tally = parse_tally(event.use, _plain(event.tally))
        if tally is None or self._store is None:
            log.info("a home coach tally was dropped", extra={"use": event.use})
            return
        who = event.who
        try:
            if not who:
                if self._people is None:
                    return
                who = await self._people.guest_for(uid, event.session, event.track)
            await self._store.keep(
                uid, event.use, who, event.session, tally.model_dump(mode="json")
            )
        except (CoachOff, Dropped, DayFull, PeopleRefused) as exc:
            log.warning("a home coach tally was not kept", extra={"error": type(exc).__name__})

    def live(self, uid: str, use: str) -> Sequence[Mapping[str, Any]]:
        bodies = self._views.get((uid, use), {})
        fresh = self._clock() - LIVE_TTL_S
        for track in [t for t, b in bodies.items() if b["at"] < fresh]:
            del bodies[track]
        return [dict(bodies[t]) for t in sorted(bodies)]

    # ---- the coach part of the bridge's state --------------------------------------------------

    def _rev(self, uid: str, wanted: Wanted) -> int:
        last = self._sent.get(uid)
        if last is not None and last.wanted == wanted:
            return last.rev
        floor = last.rev + 1 if last is not None else 0
        rev = min(MAX_REV, max(floor, int(self._clock() * 100)))
        self._sent[uid] = _Sent(wanted, rev)
        return rev

    def _state(self, uid: str, wanted: Wanted) -> CoachState:
        return CoachState(
            rev=self._rev(uid, wanted),
            uses=dict(wanted.uses),
            target=wanted.target,  # type: ignore[arg-type]
            person=wanted.person,
            all_off=wanted.all_off,
        )

    async def _wanted(self, uid: str) -> Wanted | None:
        if self._reader is not None:
            found = await self._reader(uid)
            if found is not None:
                return found
        last = self._sent.get(uid)
        return last.wanted if last is not None else None

    async def push(
        self,
        uid: str,
        *,
        uses: Mapping[str, Sequence[str]],
        target: TrackTarget,
        all_off: bool,
    ) -> None:
        state = self._state(uid, Wanted.of(uses, target, all_off))
        if self._caller is None:
            return
        try:
            await self._caller.call(
                uid, "POST", STATE_PATH, {"coach": state.model_dump(mode="json")}
            )
        except HomeUnavailable:
            log.info("the coach switches will reach the laptop at its next heartbeat")

    async def state_part(self, uid: str) -> BridgeState:
        wanted = await self._wanted(uid)
        return BridgeState() if wanted is None else BridgeState(coach=self._state(uid, wanted))


def _plain(obj: Any) -> Any:
    if isinstance(obj, Mapping):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_plain(v) for v in obj]
    return obj


__all__ = ["LIVE_TTL_S", "HomeLive", "Reader", "Wanted"]
