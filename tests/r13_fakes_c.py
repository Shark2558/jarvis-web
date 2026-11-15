# tests/r13_fakes_c.py -- R13 Part C's fakes (imported bare: `from r13_fakes_c import ...`). Every
# clock is FIXED (`r13_fakes.ist`, `FixedClock`); nothing here talks to Google or Open-Meteo.
#
#   N                         the pilot's pieces by a short name (N.shirt_lb, N.trousers, ...)
#   RING                      a test keyring (32 distinct bytes)
#   FakeGoogle                his calendar list and events; records every request (GET only)
#   FakeFetcher, forecast()   Open-Meteo's answer for two local days, recorded calls
#   RecordingNotifier         every alert (kind, words)
#   world(...)                the styling part built through `build_with` on the seeded in-memory
#                             store (the pilot set + a brown belt), its refresh bound to the store,
#                             a real gateway with its tools, R11's OutsideStore with a place
from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

from r11_fakes import reads_over
from r13_fakes import IST, PILOT, PLACES, UID, FixedClock, MemoryWardrobeStore, ev, ist, piece
from r13_fakes import seeded_store as _seeded

from jarvis.config import Settings
from jarvis.core.guardrails import ConfirmationGate
from jarvis.helpers.house.fetch import Fetched, FetchError
from jarvis.helpers.house.models import Outside, Place
from jarvis.helpers.house.store import OutsideStore
from jarvis.keyring import Keyring
from jarvis.llm.base import ToolCall
from jarvis.notify.ports import Delivery, Signal
from jarvis.storage.docs import DocTx, MemoryDocs
from jarvis.tools.audit import AuditLog
from jarvis.tools.gateway import Gateway, GatewayResult
from jarvis.tools.policy import Effect, Policy, PolicyRule
from jarvis.tools.registry import ToolRegistry
from jarvis.wardrobe.model import Piece
from jarvis.wardrobe.ports import Commit, Committed, WardrobeContext, WardrobePart
from jarvis.wardrobe.states import EventKind, State

RING = Keyring(bytes(range(40, 72)))
SCOPE = f"{UID}:sess_c"
_TRAY = PLACES[3].id
BROWN_BELT = piece("wi_0000000000b1", "belt", label="Brown belt", colour="brown", place=_TRAY)
_NAMES = (
    "shirt_lb", "shirt_white", "shirt_navy", "tee", "trousers", "jeans", "kurta", "pyjama",
    "vest1", "vest2", "under", "sock_bl", "sock_br", "sock_gl", "sock_gr", "shoe_l", "shoe_r",
    "snk_l", "snk_r", "belt", "watch", "rain_jacket", "blazer", "shorts",
)  # fmt: skip
N = SimpleNamespace(
    **{n: p.id for n, p in zip(_NAMES, PILOT, strict=True)}, brown_belt=BROWN_BELT.id
)
SHOES, SNEAKERS = (N.shoe_l, N.shoe_r), (N.snk_l, N.snk_r)
BLACK_SOCKS, GREY_SOCKS = (N.sock_bl, N.sock_br), (N.sock_gl, N.sock_gr)
KURTA_SET = "ws_00000001"


# ---- Google Calendar ---------------------------------------------------------------------------
@dataclass
class FakeGoogle:
    """`calendars`: (id, summary, primary); `events`: calendar id -> raw Google items. Records
    (method, url, params) of every request; `fail` raises."""

    calendars: list[tuple[str, str, bool]] = field(
        default_factory=lambda: [("primary-id@example.com", "Personal", True),
                                 ("work-cal@example.com", "Work", False)]
    )  # fmt: skip
    events: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    calls: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    fail: bool = False

    async def request(
        self, uid: str, method: str, url: str, *, params: dict[str, Any] | None = None, **_: Any
    ) -> Any:
        self.calls.append((method, url, dict(params or {})))
        if self.fail:
            raise RuntimeError("Google is down")
        if url.endswith("/users/me/calendarList"):
            return {"items": [{"id": i, "summary": s, "primary": p} for i, s, p in self.calendars]}
        for cal, items in self.events.items():
            from urllib.parse import quote

            if f"/calendars/{quote(cal, safe='')}/events" in url:
                return {"items": items}
        return {"items": []}


def gevent(
    ident: str, start: datetime, hours: float = 1.0, *, title: str = "", location: str = "",
    updated: str = "2026-11-10T08:00:00Z", all_day: date | None = None,
) -> dict[str, Any]:  # fmt: skip
    """One Google Calendar item (a timed event, or an all-day one on `all_day`)."""
    if all_day is not None:
        after = (all_day + timedelta(days=1)).isoformat()
        when: dict[str, Any] = {"start": {"date": all_day.isoformat()}, "end": {"date": after}}
    else:
        end = start + timedelta(hours=hours)
        when = {"start": {"dateTime": start.isoformat()}, "end": {"dateTime": end.isoformat()}}
    return {"id": ident, "status": "confirmed", "updated": updated, "summary": title,
            "location": location, **when}  # fmt: skip


# ---- Open-Meteo --------------------------------------------------------------------------------
def forecast(first: date, days: Sequence[tuple[float, Sequence[int]]]) -> bytes:
    """Open-Meteo's JSON for len(days) local days from `first`: each (t_max, hours with rain)."""
    times, precip, prob, temp = [], [], [], []
    for n, (t_max, rain) in enumerate(days):
        d = first + timedelta(days=n)
        for h in range(24):
            times.append(f"{d.isoformat()}T{h:02d}:00")
            precip.append(3.0 if h in rain else 0.0)
            prob.append(80 if h in rain else 5)
            temp.append(t_max - 4)
    daily = {
        "time": [(first + timedelta(days=n)).isoformat() for n in range(len(days))],
        "temperature_2m_max": [t for t, _ in days],
        "apparent_temperature_max": [t for t, _ in days],
        "precipitation_sum": [3.0 * len(r) for _, r in days],
    }
    hourly = {"time": times, "temperature_2m": temp, "apparent_temperature": temp,
              "precipitation": precip, "precipitation_probability": prob,
              "wind_gusts_10m": [10.0] * len(times)}  # fmt: skip
    return json.dumps({"hourly": hourly, "daily": daily}).encode()


@dataclass
class FakeFetcher:
    body: bytes | Callable[[], bytes] = b"{}"
    fail: bool = False
    calls: list[tuple[str, dict[str, str]]] = field(default_factory=list)

    async def get(
        self, url: str, *, params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None, cap: int, timeout_s: float,
    ) -> Fetched:  # fmt: skip
        self.calls.append((url, dict(params or {})))
        if self.fail:
            raise FetchError("Open-Meteo is down")
        body = self.body() if callable(self.body) else self.body
        return Fetched(200, body)


# ---- alerts ------------------------------------------------------------------------------------
@dataclass
class RecordingNotifier:
    sent: list[tuple[str, str]] = field(default_factory=list)

    async def notify(self, uid: str, signal: Signal, message: str, **_: Any) -> Delivery:
        self.sent.append((signal.kind, message))
        return Delivery(action="ring", reason="test")

    def kinds(self) -> list[str]:
        return [k for k, _ in self.sent]


# ---- the world ---------------------------------------------------------------------------------
class Rules:
    """His permission rows for the governed reads (`calendar_list_events`)."""

    def __init__(self) -> None:
        self.rules: list[PolicyRule] = []

    def set(self, tool: str, effect: Effect) -> None:
        self.rules = [r for r in self.rules if r.tool_pattern != tool]
        self.rules.append(PolicyRule(tool_pattern=tool, effect=effect))

    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        return list(self.rules)


@dataclass
class World:
    store: MemoryWardrobeStore
    clock: FixedClock
    docs: MemoryDocs
    ctx: WardrobeContext
    part: WardrobePart
    google: FakeGoogle
    fetcher: FakeFetcher
    notifier: RecordingNotifier
    audit: AuditLog
    rows: Rules
    outside: OutsideStore | None
    gw: Gateway = field(init=False)

    def __post_init__(self) -> None:
        reg = ToolRegistry()
        for t in self.part.tools:
            reg.register(t)
        self.gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=self.audit)

    @property
    def refresh(self) -> Any:
        return self.part.services["refresh"]

    @property
    def styling(self) -> Any:
        return self.refresh.styling

    async def call(self, name: str, **args: Any) -> GatewayResult:
        return await self.gw.execute(ToolCall(id="c", name=name, arguments=args), scope=SCOPE)

    async def move(
        self, pid: str, kind: EventKind, *, to: State | None = None, plan: str | None = None,
        at: datetime | None = None, verified: bool = True,
    ) -> Committed:  # fmt: skip
        e = ev(pid, kind, at or self.clock(), to=to, plan=plan, verified=verified)

        async def fn(view: Any, tx: DocTx) -> Commit:
            return Commit(events=(e,))

        return await self.store.transact(UID, fn)

    async def pieces(self) -> dict[str, Piece]:
        return dict((await self.store.view(UID)).pieces)

    async def add(self, *extra: Piece) -> None:
        async def fn(view: Any, tx: DocTx) -> Commit:
            events = tuple(ev(p.id, "registered", self.clock(), place=p.place) for p in extra)
            return Commit(events=events, records=extra)

        await self.store.transact(UID, fn)

    async def edit(self, pid: str, **fields: Any) -> None:
        """Change a record's attributes (Part A's edit, done here as the fakes set records up)."""
        view = await self.store.view(UID)
        rec = view.pieces[pid].model_copy(update=fields)

        async def fn(view: Any, tx: DocTx) -> Commit:
            return Commit(records=(rec,))

        await self.store.transact(UID, fn)


def settings(**over: Any) -> Settings:
    return Settings(_env_file=None, **over)  # type: ignore[call-arg]


def _zone(z: ZoneInfo) -> Callable[[str], Any]:
    async def zone(uid: str) -> ZoneInfo:
        return z

    return zone


async def outside_with_place(docs: MemoryDocs) -> OutsideStore:
    out = OutsideStore(docs, RING)
    place = Place(district="Pune", state="Maharashtra", lat=18.52, lon=73.86)
    await out.change(UID, lambda o: Outside(place=place))
    return out


async def world(
    *,
    at: datetime | None = None,
    place: bool = True,
    keyring: Keyring | None = RING,
    s: Settings | None = None,
    fetch: bytes | None = None,
    google: FakeGoogle | None = None,
    zone: ZoneInfo = IST,
) -> World:
    """The seeded store (pilot + brown belt) at 15 Nov 2026 09:00 IST, then the clock at `at`
    (16 Nov 2026 09:00 IST unless given)."""
    from jarvis.wardrobe.styling.part import build_with

    clock = FixedClock(ist(2026, 11, 15, 9, 0))
    docs = MemoryDocs()
    store, _ = await _seeded(docs, clock)
    clock.set(at or ist(2026, 11, 16, 9, 0))
    rows, audit, notifier = Rules(), AuditLog(), RecordingNotifier()
    g = google or FakeGoogle()
    reads = reads_over(lambda: rows, audit, now=clock)
    outside = await outside_with_place(docs) if place else None
    fetcher = FakeFetcher(fetch or forecast(clock().astimezone(zone).date(), [(30, ()), (30, ())]))
    ctx = WardrobeContext(
        s=s or settings(), docs=docs, keyring=keyring, audit=audit, now=clock, zone=_zone(zone),
        state={"google": g}.get, notifier=lambda: notifier, reads=lambda: reads,
        outside=lambda: outside, store=lambda: store,
    )  # fmt: skip
    part = build_with(ctx, fetcher=fetcher)
    refresh = part.services.get("refresh")
    store.bind(observers=[refresh] if refresh is not None else [])
    w = World(store, clock, docs, ctx, part, g, fetcher, notifier, audit, rows, outside)
    await w.add(BROWN_BELT)
    return w


def plan_ids(doc: Any) -> list[str]:
    return [p.id for p in doc.plans]


__all__ = [
    "BLACK_SOCKS",
    "BROWN_BELT",
    "GREY_SOCKS",
    "KURTA_SET",
    "RING",
    "SCOPE",
    "SHOES",
    "SNEAKERS",
    "UID",
    "FakeFetcher",
    "FakeGoogle",
    "N",
    "RecordingNotifier",
    "Rules",
    "World",
    "forecast",
    "gevent",
    "ist",
    "outside_with_place",
    "plan_ids",
    "settings",
    "world",
]
