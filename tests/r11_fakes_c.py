# tests/r11_fakes_c.py -- R11 Part C's own fakes (docs/plans/r11-free-helpers.md, Part C: nudges).
# Shared by tests/test_r11_c_*.py and evals/r11_helpers/nudges.py. Imports I0's shared fakes
# (`r11_fakes`), never copies them. Made-up data only: no real names, places or numbers.
#
# - `FakeCalendar`: the `CalendarSource` port; events by local day, counts its fetches.
# - `FakeRain`: the `RainSource` port; rainy local days.
# - `FakePending`: a `PendingSource` with fixed items (what Part A's sources give).
# - `keyring()`: a test keyring (a fixed, obviously fake root).
# - `part(...)`: Part C built on I0's `ctx` fakes, with the fakes above; returns a `Rig`.
# - `run_tool(...)`: a Part C tool run as the gateway runs it (the owner's tool context).
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from r11_fakes import UID, Clock, FakeNotifier, ctx

from jarvis.helpers.ports import HelperContext, HelperPart, PendingItem
from jarvis.keyring import Keyring
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.base import Tool
from jarvis.tools.context import tool_context

IST = ZoneInfo("Asia/Kolkata")
FAKE_ROOT = bytes(range(101, 133))  # 32 distinct bytes: a test key, never a real one


def keyring() -> Keyring:
    return Keyring(FAKE_ROOT)


def at_ist(day: date, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=IST).astimezone(UTC)


@dataclass(frozen=True)
class Planned:
    """One event in the fake calendar, in IST on its day."""

    title: str
    start: str
    end: str
    own: bool = True
    ident: str = ""


@dataclass
class FakeCalendar:
    days: dict[date, list[Planned]] = field(default_factory=dict)
    every_day: list[Planned] = field(default_factory=list)
    fail: bool = False
    fetches: int = 0

    async def events(self, uid: str, start: datetime, end: datetime) -> list[Any]:
        from jarvis.helpers.nudges.calendar import CalEvent

        self.fetches += 1
        if self.fail:
            raise RuntimeError("calendar down")
        day = start.astimezone(IST).date()
        out = []
        for i, p in enumerate([*self.every_day, *self.days.get(day, [])]):
            out.append(
                CalEvent(
                    key=f"{day.isoformat()}-{p.ident or i}",
                    title=p.title,
                    start=at_ist(day, p.start),
                    end=at_ist(day, p.end),
                    own=p.own,
                )
            )
        return [e for e in out if e.end > start and e.start < end]


@dataclass
class FakeRain:
    rainy: set[date] = field(default_factory=set)
    unknown: bool = False

    async def rain_likely(self, uid: str, start: datetime, end: datetime) -> bool | None:
        if self.unknown:
            return None
        return start.astimezone(IST).date() in self.rainy


@dataclass
class FakePending:
    items: list[PendingItem] = field(default_factory=list)
    name: str = "today"
    fail: bool = False

    async def pending(self, uid: str, now: datetime) -> Sequence[PendingItem]:
        if self.fail:
            raise RuntimeError("pending down")
        return list(self.items)


@dataclass
class Rig:
    part: HelperPart
    ctx: HelperContext
    notifier: FakeNotifier
    docs: MemoryDocs
    clock: Clock
    calendar: FakeCalendar
    rain: FakeRain
    pending: FakePending

    def tool(self, name: str) -> Tool:
        return next(t for t in self.part.tools if t.name == name)

    def job(self, name: str) -> Any:
        return next(j for j in self.part.clock_jobs if j.name == name)

    def rebuilt(self) -> Rig:
        """A restart: a fresh part (new caches) on the same documents, clock and fakes."""
        from jarvis.helpers.nudges import part as nudges_part

        fresh = nudges_part.build(self.ctx, calendar=self.calendar, rain=self.rain)
        return replace(self, part=fresh)


def part(
    *,
    sealed: bool = True,
    calendar: FakeCalendar | None = None,
    rain: FakeRain | None = None,
    pending: FakePending | None = None,
    policy: bool = True,
    at: datetime | None = None,
    **over: Any,
) -> Rig:
    """`over`: Settings fields only (I0's `ctx` passes them to Settings)."""
    from jarvis.helpers.nudges import part as nudges_part

    pend = pending or FakePending()
    c, notifier, docs, clock = ctx("nudges", pending=(pend,), **over)
    notifier.policy = policy  # the real policy: quiet hours drop a nudge, the day rings it
    if at is not None:
        clock.at = at
    if sealed:
        c = replace(c, keyring=keyring())
    cal, wet = calendar or FakeCalendar(), rain or FakeRain()
    built = nudges_part.build(c, calendar=cal, rain=wet)
    return Rig(built, c, notifier, docs, clock, cal, wet, pend)


async def run_tool(rig: Rig, name: str, **args: Any) -> Any:
    tool = rig.tool(name)
    tool.validate(args)
    with tool_context(f"{UID}:s1"):
        return await tool.run(args)


async def run_phrase(rig: Rig, text: str) -> list[str]:
    """What No-AI mode does with `text`: Part C's phrases first (D18), each call run as the
    gateway runs it. The tool names, in order (a reminder would show as `reminder_add`)."""
    from jarvis.offline.rules import route_no_ai

    route = route_no_ai(text, rig.clock().astimezone(IST), extra=rig.part.phrases)
    for call in route.calls:
        if any(t.name == call.tool for t in rig.part.tools):
            await run_tool(rig, call.tool, **call.arguments)
    return [c.tool for c in route.calls]


# ---- the 14-day simulation (plan "Tests and evals", nudges) --------------------------------------
SIM_START = date(2026, 10, 26)  # a Monday; 14 days, two Sundays
SIM_CAPS = {"nudge_standup": 10, "nudge_hydrate": 8}
SIM_IDEAS = (
    ("Read a novel", 45, "indoor"),
    ("Cycle by the lake", 60, "outdoor"),
    ("Long hike", 240, "outdoor"),
    ("Sketch", 30, "any"),
)
RAINY = (2, 5, 9)
COUNTED = ("rang", "silent")
_OUTDOOR = ("Cycle by the lake", "Long hike")


def sim_day(offset: int) -> date:
    return date.fromordinal(SIM_START.toordinal() + offset)


@dataclass
class Sim:
    rig: Rig
    runs: list[datetime] = field(default_factory=list)
    texts: list[tuple[datetime, str, str]] = field(default_factory=list)  # (run, kind, text)
    phrases: list[list[str]] = field(default_factory=list)
    restarts: int = 0


def _sim_rig() -> Rig:
    cal = FakeCalendar(
        every_day=[
            Planned("Evening walk", "17:00", "17:45", own=True, ident="walk"),
            Planned("Dinner with friends", "19:30", "21:00", own=False, ident="dinner"),
        ],
        days={
            day: [Planned("Team stand-up", "09:45", "10:00", own=False, ident="standup")]
            for day in map(sim_day, range(14))
            if day.weekday() <= 4  # Monday to Friday
        },
    )
    rain = FakeRain(rainy={sim_day(d) for d in RAINY})
    pending = FakePending([PendingItem("today", "File the tax return", "today")])
    return part(calendar=cal, rain=rain, pending=pending, nudges_max_per_day=24)


async def _setup(rig: Rig) -> None:
    from jarvis.helpers.gate import GateStore
    from jarvis.helpers.nudges.models import Idea

    svc = rig.part.services["service"]
    ideas = tuple(Idea.new(text, minutes, place) for text, minutes, place in SIM_IDEAS)  # type: ignore[arg-type]
    await svc.store.change(UID, lambda s: s.with_ideas(ideas))
    for kind in ("nudge_standup", "nudge_hydrate", "nudge_focus", "nudge_free_time"):
        await svc.store.change(UID, lambda s, k=kind: s.changed(k, {"on": True}))
    await svc.store.change(UID, lambda s: s.changed("nudge_standup", {"meeting": True}))
    await svc.store.change(UID, lambda s: s.changed("nudge_activity", {"on": True}))
    await GateStore(rig.docs).set_caps(UID, SIM_CAPS)


async def _events_of_the_day(sim: Sim, day: int, local: datetime) -> None:
    """What he says and taps on given days (by phrase through No-AI, or the tab's gate route)."""
    from jarvis.helpers.gate import GateStore

    rig, hhmm = sim.rig, local.strftime("%H:%M")
    gate = GateStore(rig.docs)
    said = {
        (1, "19:00"): "I did read a novel from my list",
        (2, "12:05"): "snooze the water reminder for an hour",
        (3, "13:05"): "don't remind me to stand up",
    }
    if (day, hhmm) in said:
        sim.phrases.append(await run_phrase(rig, said[(day, hhmm)]))
    if day % 2 == 0 and hhmm == "17:50":
        sim.phrases.append(await run_phrase(rig, "walk done"))
    if (day, hhmm) == (4, "12:00"):
        await gate.snooze(UID, "nudge_hydrate", 60, rig.clock())  # a tap: Snooze 1 h
    if (day, hhmm) == (8, "00:00"):
        await gate.set_caps(UID, {"nudge_hydrate": 3})
    if (day, hhmm) == (9, "00:00"):
        await gate.set_caps(UID, {"nudge_hydrate": 8})


async def _run_jobs(rig: Rig) -> None:
    for job in rig.part.clock_jobs:
        await job.run(("not-the-owner",))


async def simulate(*, days: int = 14) -> Sim:
    """14 days on the 5-minute clock with up to 40 s of Scheduler jitter. After every run that sent
    something the instance "restarts" and the Scheduler retries the same run (a fresh part, the
    same documents): claims must keep that from sending twice."""
    rig = _sim_rig()
    await _setup(rig)
    sim = Sim(rig)
    start = at_ist(SIM_START, "00:00")
    for tick in range(days * 288):
        rig.clock.at = start + timedelta(minutes=5 * tick, seconds=(tick * 37) % 41)
        local = rig.clock().astimezone(IST)
        await _events_of_the_day(sim, tick // 288, local.replace(second=0))
        before = len(rig.notifier.calls)
        sim.runs.append(rig.clock.at)
        await _run_jobs(rig)
        if len(rig.notifier.calls) > before:
            sim.restarts += 1
            await _run_jobs(rig.rebuilt())
        for _, kind, text, _ in rig.notifier.calls[before:]:
            sim.texts.append((rig.clock.at, kind, text))
    return sim


def expected(days: int = 14) -> dict[tuple[str, datetime], None]:
    """Every nudge the owner's settings and his words above say goes out, worked out by hand."""
    out: dict[tuple[str, datetime], None] = {}
    for d in range(days):
        day = sim_day(d)
        wd = day.weekday()
        if wd <= 5:
            for h in range(10, 18):
                if not (d == 3 and h >= 13):  # "don't remind me to stand up" at 13:05
                    out[("nudge_standup", at_ist(day, f"{h}:30"))] = None
            waters = ["11:00", "12:30", "14:00", "15:30", "17:00"]
            if d in (2, 4):
                waters.remove("12:30")  # snoozed by phrase (day 2) and by a tap (day 4)
            if d == 8:
                waters = waters[:3]  # his cap of 3 that day
            out.update({("nudge_hydrate", at_ist(day, w)): None for w in waters})
            out.update({("nudge_focus", at_ist(day, t)): None for t in ("10:00", "15:00")})
        if wd <= 4:
            out[("nudge_standup", at_ist(day, "09:35"))] = None  # the meeting variant
        out[("nudge_free_time", at_ist(day, "18:00"))] = None
        if d % 2 == 1:
            out[("nudge_activity", at_ist(day, "18:00"))] = None  # no check-in on odd days
    return out


def _first_run(runs: list[datetime], due: datetime) -> datetime | None:
    return next((r for r in runs if r >= due), None)


def _minute(at: datetime) -> str:
    return at.astimezone(UTC).replace(second=0, microsecond=0).isoformat()


async def judge(sim: Sim, days: int = 14) -> list[str]:
    """Everything the plan asks of 14 days, as failures (empty = all held)."""
    from jarvis.helpers.gate import GateStore

    gate = GateStore(sim.rig.docs)
    log = [(d, e) for d, sends in await gate.days(UID) for e in sends]
    sent = [e for _, e in log if e.get("o") in COUNTED]
    fails: list[str] = []
    seen: dict[tuple[str, str], int] = {}
    for e in sent:
        seen[(e["k"], e["due"])] = seen.get((e["k"], e["due"]), 0) + 1
    want = expected(days)
    for (kind, due), _ in want.items():
        n = seen.get((kind, _minute(due)), 0)
        first = _first_run(sim.runs, due)
        at = [e["at"] for e in sent if e["k"] == kind and e["due"] == _minute(due)]
        if n == 0:
            fails.append(f"missed {kind} due {due.astimezone(IST):%m-%d %H:%M}")
        elif n > 1:
            fails.append(f"sent twice: {kind} due {due.astimezone(IST):%m-%d %H:%M}")
        elif first is None or at[0] != _minute(first):
            fails.append(f"not in the first run at or after due: {kind} {due.astimezone(IST)}")
    wanted = {(k, _minute(d)) for k, d in want}
    fails += [
        f"unexpected {e['k']} due {e['due']}" for e in sent if (e["k"], e["due"]) not in wanted
    ]
    fails += [f"early {e['k']} {e['at']} < {e['due']}" for e in sent if e["at"] < e["due"]]
    from jarvis.helpers.gate import fortnight

    line = fortnight(await gate.days(UID), sim_day(days - 1).isoformat(), max_per_day=24)
    if line["nudge_days_within_limits"] != days:
        fails.append(f"nudges inside the limits on {line['nudge_days_within_limits']} of {days}")
    fails += _caps(log, sim)
    fails += _free_time(sim)
    fails += _phrases(sim)
    return fails


def _caps(log: list[tuple[str, dict[str, str]]], sim: Sim) -> list[str]:
    fails: list[str] = []
    by_day: dict[str, list[dict[str, str]]] = {}
    for day, e in log:
        if e.get("o") in COUNTED:
            by_day.setdefault(day, []).append(e)
    for day, sends in by_day.items():
        caps = {**SIM_CAPS, "nudge_hydrate": 3 if day == "2026-11-03" else 8}
        for kind, cap in {**dict.fromkeys(("nudge_activity",), 3), **caps}.items():
            if sum(1 for e in sends if e["k"] == kind) > cap:
                fails.append(f"{kind} over its cap of {cap} on {day}")
        if len(sends) > 24:
            fails.append(f"more than 24 nudges on {day}")
        ats = sorted(e["at"] for e in sends)
        for i, at in enumerate(ats):
            hour = (datetime.fromisoformat(at) - timedelta(hours=1)).isoformat()
            if sum(1 for x in ats[: i + 1] if x > hour) > 4:
                fails.append(f"more than 4 nudges in the hour before {at}")
    if not any(e.get("o") == "capped" for _, e in log):
        fails.append("his cap of 3 water nudges was never needed (the case proves nothing)")
    if sim.restarts < 14:
        fails.append(f"only {sim.restarts} restarts were simulated")
    return fails


def _free_time(sim: Sim) -> list[str]:
    fails: list[str] = []
    rainy = {sim_day(d) for d in RAINY}
    for at, kind, text in sim.texts:
        if kind != "nudge_free_time":
            continue
        day = at.astimezone(IST).date()
        if "Long hike" in text:
            fails.append(f"{day}: an idea longer than the 90-minute gap")
        if day in rainy and any(o in text for o in _OUTDOOR):
            fails.append(f"{day}: an outdoor idea on a rainy day")
        offset = day.toordinal() - SIM_START.toordinal()
        if offset in (2, 3) and "Read a novel" in text:
            fails.append(f"{day}: an idea done in the last 3 days")
    return fails


def _phrases(sim: Sim) -> list[str]:
    flat = [tool for calls in sim.phrases for tool in calls]
    fails = [] if "reminder_add" not in flat else ["a phrase set a reminder"]
    if ["nudge_stop"] not in sim.phrases or ["nudge_snooze"] not in sim.phrases:
        fails.append(f"the snooze and stop phrases didn't reach their tools: {sim.phrases}")
    return fails
