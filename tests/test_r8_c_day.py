# tests/test_r8_c_day.py -- R8 row 182 (docs/plans/r8-vision.md 2.1, 4.7, D12; ROWS.md): the
# activity timeline from the home camera, the day strip and the brief's line.
#   - the plan's check: a synthetic 8-hour day is labelled right for >= 90 % of its minutes; only
#     kind, start and end are kept
#   - the workbook's check (ROWS.md): "The day's timeline shows." -> GET /v1/coach/day
#   - the strip joins the kept tallies (the newest says last), marks uncovered time "off", sums
#     each kind and finds the longest sitting stretch; screen time rides along (row 183)
#   - the brief's one line: totals only, never posture, a program's name or a time of day
from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from r8_fakes import KEY, SESSION
from r8_fakes_c import frames

from jarvis.coach.day import DayService, ScreenView, Stretch, hm, longest_sitting, strip
from jarvis.coach.home import activity as A
from jarvis.coach.ports import ScreenTimeDay
from jarvis.coach.usecases import parse_tally
from jarvis.home.ports import MAX_EVENT_BYTES, CoachReport

IST = ZoneInfo("Asia/Kolkata")
DAY = date(2026, 11, 26)
NINE = int(datetime(2026, 11, 26, 9, 0, tzinfo=IST).timestamp())
WORKDAY = [  # 8 hours: work, a phone call, lunch, away, more work (480 minutes)
    ("desk", 85 * 60), ("phone", 7 * 60), ("slouch", 8 * 60), ("desk", 40 * 60),
    ("eating", 25 * 60), ("away", 45 * 60), ("desk", 70 * 60), ("phone", 3 * 60),
    ("hidden", 2 * 60), ("desk", 30 * 60), ("away", 12 * 60), ("forward", 6 * 60),
    ("desk", 80 * 60), ("eating", 12 * 60), ("phone", 5 * 60), ("desk", 50 * 60),
]  # fmt: skip


def feed(blocks: list[tuple[str, float]], *, seed: int = 7, start: int = NINE) -> tuple[
    A.ActivityCoach, A.ActivityState, dict[int, str]
]:  # fmt: skip
    coach, state = A.ActivityCoach(), None
    truth: dict[int, Counter[str]] = {}
    for t, kind, results in frames(blocks, start=start, seed=seed):
        truth.setdefault(int(t) // 60, Counter())[kind] += 1
        for r in results:
            state = coach.on_result(r, state)
    assert state is not None
    return coach, state, {m: c.most_common(1)[0][0] for m, c in truth.items()}


def labels_of(tally: dict[str, Any]) -> dict[int, str]:
    out = {}
    for s in tally["segments"]:
        for m in range(s["start"] // 60, s["end"] // 60):
            out[m] = s["kind"]
    return out


@pytest.mark.parametrize("seed", [7, 19, 31])
def test_an_8_hour_day_is_labelled_right_for_nine_minutes_in_ten(seed: int) -> None:
    assert sum(s for _, s in WORKDAY) == 8 * 3600
    coach, state, truth = feed(WORKDAY, seed=seed)
    tally = coach.summary(state)["tally"]
    assert tally is not None
    got = labels_of(tally)
    right = sum(1 for m, kind in truth.items() if got.get(m) == kind)
    assert right / len(truth) >= 0.9, (right, len(truth))
    assert {s["kind"] for s in tally["segments"]} == {"desk", "away", "phone", "eating"}


def test_only_kind_start_and_end_are_kept_and_the_tally_fits_its_model() -> None:
    coach, state, _ = feed(WORKDAY[:6])
    out = coach.summary(state)
    tally = parse_tally("activity", out["tally"])
    assert tally is not None and tally.segments  # type: ignore[attr-defined]
    assert all(set(s) == {"kind", "start", "end"} for s in out["tally"]["segments"])  # type: ignore[index]
    flat = json.dumps(out)
    for key in ('"x"', '"y"', '"box"', '"points"', '"visibility"', "cell_phone", "bowl"):
        assert key not in flat


def test_its_report_fits_the_home_wire_even_at_its_segment_cap() -> None:
    blocks = [("desk" if i % 2 else "phone", 120.0) for i in range(260)]  # flapping all day
    coach, state, _ = feed(blocks)
    out = coach.summary(state)
    assert out["tally"] is not None and len(out["tally"]["segments"]) == A.MAX_SEGMENTS
    segs = out["tally"]["segments"]
    assert all(a["end"] <= b["start"] for a, b in zip(segs, segs[1:], strict=False))
    report = CoachReport(type="coach", id="e1", at=float(NINE), camera="desk_cam",
                         use="activity", session=SESSION, track=0, who="me",
                         view=tuple(out["view"]), tally=out["tally"])  # fmt: skip
    assert len(report.model_dump_json()) < MAX_EVENT_BYTES
    assert parse_tally("activity", out["tally"]) is not None


def test_a_gap_with_no_frame_is_left_uncovered_not_called_away() -> None:
    coach = A.ActivityCoach()
    state = None
    for blocks, start in (([("desk", 600.0)], NINE), ([("desk", 600.0)], NINE + 3600)):
        for _, _, results in frames(blocks, start=start):
            for r in results:
                state = coach.on_result(r, state)
    tally = coach.summary(state)["tally"]
    assert tally is not None
    kinds = [(s["kind"], s["start"] - NINE, s["end"] - NINE) for s in tally["segments"]]
    assert kinds[0][0] == "desk" and kinds[-1][0] == "desk" and "away" not in {k for k, *_ in kinds}
    assert any(b[1] - a[2] >= 2900 for a, b in zip(kinds, kinds[1:], strict=False))


# ---- the day strip -----------------------------------------------------------------------------
def _item(segs: list[tuple[str, int, int]], kept: str, who: str = "me") -> dict[str, Any]:
    return {
        "use": "activity",
        "who": who,
        "kept_at": kept,
        "tally": {
            "started_at": segs[0][1],
            "ended_at": segs[-1][2],
            "segments": [{"kind": k, "start": a, "end": b} for k, a, b in segs],
        },
    }


def test_the_newest_tally_says_last_and_uncovered_time_is_off() -> None:
    h = 3600
    first = _item([("desk", NINE, NINE + h)], "2026-11-26T04:00:00")  # every 15 min: cumulative
    later = _item([("desk", NINE, NINE + h), ("phone", NINE + h - 600, NINE + h + 300)],
                  "2026-11-26T05:00:00")  # fmt: skip
    after = _item([("desk", NINE + 3 * h, NINE + 4 * h)], "2026-11-26T09:00:00")
    guest = _item([("eating", NINE, NINE + 4 * h)], "2026-11-26T09:00:00", who="gst_0123456789ab")
    junk = {**_item([("desk", NINE, NINE + h)], "2026-11-26T10:00:00"), "tally": {"x": 1}}
    got = strip([after, guest, later, first, junk], DAY, IST)
    kinds = [(s.kind, s.start - NINE, s.end - NINE) for s in got.stretches]
    assert kinds == [("desk", 0, h - 600), ("phone", h - 600, h + 300), ("off", h + 300, 3 * h),
                     ("desk", 3 * h, 4 * h)]  # fmt: skip
    assert got.totals == {"desk": 2 * h - 600, "away": 0, "phone": 900, "eating": 0,
                          "off": 2 * h - 300}  # fmt: skip
    assert got.longest == Stretch("desk", NINE, NINE + h + 300)
    assert strip([guest], DAY, IST, who="gst_0123456789ab").totals["eating"] == 4 * h  # type: ignore[index]


def test_a_short_walk_does_not_break_a_sitting_stretch_but_a_long_one_does() -> None:
    s = [Stretch("desk", 0, 3000), Stretch("away", 3000, 3100), Stretch("phone", 3100, 4000),
         Stretch("away", 4000, 4400), Stretch("desk", 4400, 5000)]  # fmt: skip
    assert longest_sitting(s) == Stretch("desk", 0, 4000)
    assert longest_sitting([]) is None and hm(20_700) == "5 h 45 min" and hm(1500) == "25 min"


def test_a_day_outside_his_zone_starts_at_his_midnight() -> None:
    got = strip([], DAY, IST)
    assert datetime.fromtimestamp(got.start, IST).hour == 0 and got.end - got.start == 86_400
    assert got.stretches == () and got.longest is None


class FakeScreen:
    def __init__(self, state: str = "ok") -> None:
        self.st, self.asked = state, 0

    async def state(self, uid: str) -> str:
        return self.st

    async def day(self, uid: str, day: str) -> ScreenTimeDay | None:
        self.asked += 1
        progs = {"chrome": 200.0, "Code": 150.5, "Teams": 40.0, "Excel": 30.0, "explorer": 5.0,
                 "Notepad": 1.0}  # fmt: skip
        return ScreenTimeDay(day, active_minutes=370.25, programs=progs)


def _service(*, sealed: bool = True, screen: Any = None) -> tuple[DayService, Any]:
    from jarvis.coach.store import CoachStore
    from jarvis.keyring import Keyring
    from jarvis.storage.docs import MemoryDocs

    evening = datetime(2026, 11, 26, 13, 0, tzinfo=UTC)  # 18:30 in Kolkata
    store = CoachStore(MemoryDocs(), Keyring(KEY) if sealed else None, now=lambda: evening)
    return DayService(store, screen, tz="Asia/Kolkata", now=lambda: evening), store


async def test_the_service_joins_his_kept_day_and_screen_time() -> None:
    svc, store = _service(screen=FakeScreen())
    coach, state, _ = feed(WORKDAY)
    await store.keep("u1", "activity", "me", SESSION, coach.summary(state)["tally"])
    got = await svc.day("u1", DAY)
    assert got.totals is not None and got.totals["desk"] > 5 * 3600
    assert got.screen == ScreenView("ok", 370.2, (("chrome", 200.0), ("Code", 150.5),
                                                  ("Teams", 40.0), ("Excel", 30.0),
                                                  ("explorer", 5.0)))  # fmt: skip
    off = await _service(screen=FakeScreen("not_installed"))[0].day("u1", DAY)
    assert off.screen == ScreenView("not_installed") and off.stretches == ()
    with pytest.raises(ValueError):
        await svc.day("u1", DAY + timedelta(days=1))  # tomorrow isn't kept yet


def _client(days: DayService | None) -> Any:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from jarvis.api import coach_day
    from jarvis.api.auth import require_auth
    from jarvis.api.identity import current_user

    app = FastAPI()
    app.include_router(coach_day.router)
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[current_user] = lambda: "u1"
    app.state.coach_day = days
    return TestClient(app)


async def test_the_days_timeline_shows_on_its_route_the_workbooks_check() -> None:
    svc, store = _service(screen=FakeScreen())
    coach, state, _ = feed(WORKDAY[:5])
    await store.keep("u1", "activity", "me", SESSION, coach.summary(state)["tally"])
    c = _client(svc)
    r = c.get("/v1/coach/day", params={"day": DAY.isoformat()})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    day = r.json()["day"]
    assert [s["kind"] for s in day["stretches"]][:2] == ["desk", "phone"]
    assert day["screen"]["programs"][0] == {"name": "chrome", "minutes": 200.0}
    assert c.get("/v1/coach/day").status_code == 200  # today
    assert c.get("/v1/coach/day", params={"day": "2026-13-01"}).json()["error"] == "bad_request"
    assert c.get("/v1/coach/day", params={"who": "Shruti"}).status_code == 422  # never a name
    assert _client(None).get("/v1/coach/day").json()["error"] == "coach_off"


def test_the_route_needs_the_owner() -> None:
    from jarvis.api import coach_day
    from jarvis.api.auth import require_auth
    from jarvis.api.identity import current_user

    assert [d.dependency for d in coach_day.router.dependencies] == [require_auth]
    (route,) = coach_day.router.routes
    assert current_user in [d.call for d in route.dependant.dependencies]  # type: ignore[attr-defined]


async def test_the_brief_says_yesterday_in_one_line_without_health_or_names() -> None:
    from jarvis.coach.brief import CoachDayBrief

    svc, store = _service(screen=FakeScreen())
    coach, state, _ = feed(WORKDAY)
    await store.keep("u1", "activity", "me", SESSION, coach.summary(state)["tally"])
    lines = await CoachDayBrief(svc).lines("u1", IST, DAY + timedelta(days=1))
    assert len(lines) == 1
    line = lines[0]
    assert line.startswith("Yesterday at your desk: ") and "screen time 6 h 10 min" in line
    for never in ("chrome", "Code", "slouch", "posture", "09:", "upright"):
        assert never not in line
    assert await CoachDayBrief(svc).lines("u1", IST, DAY) == ()  # nothing seen the day before


async def test_the_brief_is_silent_without_a_key_or_when_the_day_cannot_be_read() -> None:
    from jarvis.coach.brief import CoachDayBrief
    from jarvis.coach.store import CoachUnavailable

    svc, _ = _service(sealed=False)
    assert await CoachDayBrief(svc).lines("u1", IST, DAY + timedelta(days=1)) == ()
    broken, store = _service()

    async def fail(*a: Any, **k: Any) -> list[dict[str, Any]]:
        raise CoachUnavailable()

    store.list = fail  # type: ignore[method-assign]
    assert await CoachDayBrief(broken).lines("u1", IST, DAY + timedelta(days=1)) == ()
