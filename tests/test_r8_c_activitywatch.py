# tests/test_r8_c_activitywatch.py -- R8 row 183 (docs/plans/r8-vision.md 2.1, 4.7, D5, ADR-53;
# ROWS.md): screen time via ActivityWatch, against a fake ActivityWatch API (httpx MockTransport).
#   - the plan's check: per-program minutes and active time exact; window titles never leave the
#     laptop (not in the answer, not in a log line, not in the cloud); with no ActivityWatch Vitals
#     says "off until ActivityWatch is installed"
#   - the workbook's check (ROWS.md): "Top apps/sites for today show." -> the day strip's programs
#   - the bridge plugin: its one fixed route, a bad query refused in plain words, AW_URL checked,
#     an odd or slow ActivityWatch is "unreachable"; the cloud asks once a minute at most
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest

from jarvis.coach.screentime import BridgeScreenTime, offset_minutes, parse_day
from jarvis.home.ports import SCREENTIME_ROUTE, HomeOffline, HomeRefused
from jarvis.homebridge import activitywatch as AW
from jarvis.homebridge.plugins import BridgeContext, check_routes

ROOT = Path(__file__).resolve().parents[1]
IST = ZoneInfo("Asia/Kolkata")
DAY = "2026-11-26"
SECRET = "Salary slip 2026 - Private bank page"  # a window title: must never leave
WIN, AFK = "aw-watcher-window_LAPTOP-OWNER", "aw-watcher-afk_LAPTOP-OWNER"


def ist(hhmm: str, day: str = DAY) -> str:
    d = date.fromisoformat(day)
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(d.year, d.month, d.day, h, m, tzinfo=IST).astimezone(UTC).isoformat()


def ev(start: str, minutes: float, data: dict[str, Any], day: str = DAY) -> dict[str, Any]:
    return {"id": 1, "timestamp": ist(start, day), "duration": minutes * 60, "data": data}


PREV = "2026-11-25"
WINDOW_EVENTS = [
    ev("23:50", 20, {"app": "explorer.exe", "title": "Downloads"}, PREV),  # crosses midnight
    ev("09:00", 60, {"app": "chrome.exe", "title": SECRET}),
    ev("10:00", 90, {"app": "Code.exe", "title": "r8 - jarvis"}),
    ev("11:30", 30, {"app": "chrome.exe", "title": "Private"}),
    ev("12:00", 30, {"app": "Teams.exe", "title": "Call with someone"}),
    ev("23:58", 30, {"app": "chrome.exe", "title": "late"}),  # runs into tomorrow
]
AFK_EVENTS = [
    ev("23:55", 10, {"status": "not-afk"}, PREV),
    ev("08:55", 125, {"status": "not-afk"}),
    ev("11:00", 20, {"status": "afk"}),
    ev("11:20", 80, {"status": "not-afk"}),
    ev("23:58", 30, {"status": "not-afk"}),
]
BUCKETS = {
    WIN: {"id": WIN, "type": "currentwindow", "hostname": "LAPTOP-OWNER",
          "last_updated": "2026-11-26T12:00:00+00:00"},
    AFK: {"id": AFK, "type": "afkstatus", "hostname": "LAPTOP-OWNER",
          "last_updated": "2026-11-26T12:00:00+00:00"},
    "aw-watcher-web-chrome": {"type": "web.tab.current", "last_updated": "2026-11-26"},
}  # fmt: skip


class FakeAW:
    """ActivityWatch's REST API as the plugin uses it; `mode` breaks it on purpose."""

    def __init__(self, mode: str = "ok", buckets: dict[str, Any] | None = None) -> None:
        self.mode, self.buckets, self.asked = mode, buckets or BUCKETS, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request)
        if self.mode == "down":
            raise httpx.ConnectError("refused", request=request)
        if self.mode == "slow":
            raise httpx.ReadTimeout("slow", request=request)
        if self.mode == "500":
            return httpx.Response(500, text="Traceback ...")
        if self.mode == "garbage":
            return httpx.Response(200, text="<html>not json</html>")
        path = request.url.raw_path.decode().split("?")[0]
        if path == "/api/0/buckets/":
            return httpx.Response(200, json=self.buckets)
        if path == f"/api/0/buckets/{WIN}/events":
            return httpx.Response(200, json=WINDOW_EVENTS)
        if path == f"/api/0/buckets/{AFK}/events":
            return httpx.Response(200, json=AFK_EVENTS)
        return httpx.Response(404, json={"message": "no such bucket"})


def plugin(fake: FakeAW, env: dict[str, str] | None = None) -> AW.ActivityWatchPlugin:
    ctx = BridgeContext(env=env or {}, data_dir=Path("/tmp"), events=None)  # type: ignore[arg-type]
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake))
    return AW.ActivityWatchPlugin(ctx, client=client)


def query(day: str = DAY) -> dict[str, str]:
    return {"day": day, "offset": str(offset_minutes(date.fromisoformat(day), IST))}


async def serve(p: AW.ActivityWatchPlugin, q: dict[str, str]) -> dict[str, Any]:
    (route,) = p.routes()
    return await route.handler(q, None)


async def test_per_program_minutes_and_active_time_are_exact() -> None:
    fake = FakeAW()
    got = await serve(plugin(fake), query())
    # active: 00:00-00:05 + 08:55-11:00 + 11:20-12:40 + 23:58-24:00 = 5 + 125 + 80 + 2 = 212 min
    assert got == {
        "state": "ok",
        "day": DAY,
        "active_minutes": 212.0,
        "programs": [
            {"name": "chrome", "minutes": 92.0},  # 09:00-10:00, 11:30-12:00, 23:58-24:00
            {"name": "Code", "minutes": 70.0},  # 10:00-11:00 and 11:20-11:30 (afk 11:00-11:20)
            {"name": "Teams", "minutes": 30.0},
            {"name": "explorer", "minutes": 5.0},  # 00:00-00:10, at the keyboard to 00:05
        ],
    }
    start, end = AW.day_window(DAY, 330)
    params = fake.asked[1].url.params
    assert params["start"] == datetime.fromtimestamp(start, UTC).isoformat()
    assert params["end"] == datetime.fromtimestamp(end, UTC).isoformat() and end - start == 86_400
    assert fake.asked[0].url.host == "host.docker.internal" and fake.asked[0].url.port == 5600


async def test_window_titles_never_leave_the_laptop(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        got = await serve(plugin(FakeAW()), query())
        await serve(plugin(FakeAW("500")), query())
    text = json.dumps(got)
    for title in (SECRET, "Private", "r8 - jarvis", "Call with someone", "Downloads", "title"):
        assert title not in text
    logged = " ".join(r.getMessage() + json.dumps(r.__dict__, default=str) for r in caplog.records)
    assert SECRET not in logged and "Traceback" not in logged


async def test_with_no_activitywatch_it_says_not_installed() -> None:
    assert await serve(plugin(FakeAW("down")), query()) == {"state": "not_installed"}
    no_window = FakeAW(buckets={AFK: BUCKETS[AFK]})
    assert await serve(plugin(no_window), query()) == {"state": "not_installed"}


@pytest.mark.parametrize("mode", ["slow", "500", "garbage"])
async def test_an_odd_or_slow_activitywatch_is_unreachable(mode: str) -> None:
    assert await serve(plugin(FakeAW(mode)), query()) == {"state": "unreachable"}


async def test_a_bad_query_is_refused_in_plain_words() -> None:
    p = plugin(FakeAW())
    for q in ({}, {"day": DAY}, {"day": "26/11/2026", "offset": "330"},
              {"day": DAY, "offset": "9999"}, {"day": "2026-02-30", "offset": "330"}):  # fmt: skip
        with pytest.raises(HomeRefused) as refused:
            await serve(p, q)
        assert refused.value.code == "bad_request" and refused.value.message == AW.BAD_QUERY


async def test_no_afk_watcher_counts_the_window_events_as_active() -> None:
    got = await serve(plugin(FakeAW(buckets={WIN: BUCKETS[WIN]})), query())
    assert got["state"] == "ok" and got["active_minutes"] == 10 + 60 + 90 + 30 + 30 + 2


def test_aw_url_is_a_plain_address_or_nothing_is_asked() -> None:
    assert AW.base_url("") == AW.base_url(None) == "http://host.docker.internal:5600"
    assert AW.base_url("http://172.29.80.1:5600/") == "http://172.29.80.1:5600"
    for bad in ("ftp://x:5600", "http://user:pw@x:5600", "http://x:5600/api", "http://x?a=1",
                "file:///etc/passwd", "http://x:99999"):  # fmt: skip
        assert AW.base_url(bad) is None, bad


async def test_a_bad_aw_url_is_unreachable_without_a_request() -> None:
    fake = FakeAW()
    got = await serve(plugin(fake, {"AW_URL": "http://x:5600/api"}), query())
    assert got == {"state": "unreachable"} and fake.asked == []


def test_program_names_are_short_and_plain() -> None:
    assert AW.program("chrome.EXE") == "chrome" and AW.program(None) == "Unknown"
    assert AW.program("a\x00b\nc" + "x" * 80) == "abc" + "x" * 37


async def test_it_is_the_registered_plugin_of_its_one_route() -> None:
    from jarvis.homebridge.registry import PLUGINS

    ctx = BridgeContext(env={}, data_dir=Path("/tmp"), events=None)  # type: ignore[arg-type]
    made = AW.create_plugin(ctx)
    assert AW.create_plugin in PLUGINS and made.name == "activitywatch"
    assert [(r.method, r.path) for r in made.routes()] == [SCREENTIME_ROUTE]
    assert made.tasks() == () and (await made.heartbeat_part()).model_dump(exclude_none=True) == {}
    check_routes([made])
    await made.aclose()  # type: ignore[attr-defined]


def test_the_kit_ships_it_and_the_example_names_aw_url() -> None:
    from jarvis.home import kit

    files = kit.bridge_sources(ROOT / "src")
    assert "jarvis/homebridge/activitywatch.py" in files
    example = (ROOT / "deploy" / "home" / "bridge.env.example").read_text(encoding="utf-8")
    assert "\nAW_URL=\n" in example and "window titles never leave this laptop" in example


# ---- the cloud's side: BridgeScreenTime over the signed call ------------------------------------
class Caller:
    """A HomeCaller that hands the query to the plugin's handler (the signed hop in between)."""

    def __init__(self, p: AW.ActivityWatchPlugin | None, fail: Exception | None = None) -> None:
        self.p, self.fail, self.calls = p, fail, 0

    async def call(self, uid: str, method: str, path: str, body: Any = None, *,
                   query: dict[str, str] | None = None) -> dict[str, Any]:  # fmt: skip
        self.calls += 1
        assert (method, path) == SCREENTIME_ROUTE
        if self.fail is not None:
            raise self.fail
        assert self.p is not None
        return await serve(self.p, dict(query or {}))


def clock_at(day: str = DAY, hhmm: str = "18:30") -> Callable[[], float]:
    at = datetime.fromisoformat(ist(hhmm, day)).timestamp()
    return lambda: at


async def test_the_cloud_reads_the_day_once_a_minute_and_drops_nothing_but_misfits() -> None:
    caller = Caller(plugin(FakeAW()))
    st = BridgeScreenTime(caller, tz="Asia/Kolkata", clock=clock_at())
    assert await st.state("u1") == "ok"
    got = await st.day("u1", DAY)
    assert got is not None and got.active_minutes == 212.0
    assert got.programs == {"chrome": 92.0, "Code": 70.0, "Teams": 30.0, "explorer": 5.0}
    assert caller.calls == 1  # the state and the day: one call to the laptop
    with pytest.raises(ValueError):
        await st.day("u1", "yesterday")


@pytest.mark.parametrize(
    ("fail", "state"),
    [
        (HomeRefused("not_linked", "x"), "not_installed"),
        (HomeRefused("not_built", "x"), "not_installed"),
        (HomeRefused("bad_reply", "x"), "unreachable"),
        (HomeOffline(), "unreachable"),
        (RuntimeError("boom"), "unreachable"),
    ],
)
async def test_the_kit_unlinked_is_off_and_the_laptop_away_is_unreachable(
    fail: Exception, state: str
) -> None:
    st = BridgeScreenTime(Caller(None, fail), tz="Asia/Kolkata", clock=clock_at())
    assert await st.state("u1") == state and await st.day("u1", DAY) is None
    assert await BridgeScreenTime(None, tz="Asia/Kolkata", clock=clock_at()).state("u1") == (
        "not_installed"
    )


def test_a_reply_that_does_not_fit_is_dropped_never_repaired() -> None:
    good = {"state": "ok", "day": DAY, "active_minutes": 10.0,
            "programs": [{"name": "chrome", "minutes": 10.0}]}  # fmt: skip
    assert parse_day(DAY, good) is not None
    for bad in (
        {**good, "day": "2026-11-25"},
        {**good, "active_minutes": 5000},
        {**good, "programs": [{"name": "x" * 41, "minutes": 1.0}]},
        {**good, "programs": [{"name": "chrome", "minutes": 1.0, "title": SECRET}] * 30},
        {**good, "programs": [{"name": "tab\tname", "minutes": 1.0}]},
        {**good, "programs": "chrome"},
    ):
        assert parse_day(DAY, bad) is None


async def test_with_no_activitywatch_vitals_says_off_until_it_is_installed() -> None:
    from jarvis.config import Settings
    from jarvis.vitals.own import Own, OwnSources

    st = BridgeScreenTime(Caller(plugin(FakeAW("down"))), tz="Asia/Kolkata", clock=clock_at())
    own = Own(OwnSources(screen=st), Settings(_env_file=None))  # type: ignore[call-arg]
    now = datetime.fromtimestamp(clock_at()(), UTC)
    items = {i.provider.id: i for i in await own.items("u1", now, IST)}
    assert items["screen_time"].base == ("ok", "is off until ActivityWatch is installed")
    ok = BridgeScreenTime(Caller(plugin(FakeAW())), tz="Asia/Kolkata", clock=clock_at())
    items = {
        i.provider.id: i
        for i in await Own(OwnSources(screen=ok), Settings(_env_file=None)).items("u1", now, IST)
    }  # type: ignore[call-arg]  # noqa: E501
    assert items["screen_time"].base == ("ok", "")


async def test_top_programs_for_today_show_the_workbooks_check() -> None:
    from jarvis.coach.day import DayService
    from jarvis.coach.store import CoachStore
    from jarvis.storage.docs import MemoryDocs

    now = datetime.fromtimestamp(clock_at()(), UTC)
    st = BridgeScreenTime(Caller(plugin(FakeAW())), tz="Asia/Kolkata", clock=clock_at())
    svc = DayService(CoachStore(MemoryDocs(), None, now=lambda: now), st, tz="Asia/Kolkata",
                     now=lambda: now)  # fmt: skip
    day = (await svc.day("u1", now.astimezone(IST).date())).as_json()
    assert [p["name"] for p in day["screen"]["programs"]] == ["chrome", "Code", "Teams", "explorer"]
    assert day["screen"]["state"] == "ok" and day["screen"]["active_minutes"] == 212.0
    assert offset_minutes(date(2026, 11, 26) + timedelta(days=0), IST) == 330
