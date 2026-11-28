# evals/r8/desk.py
"""R8 eval, builder C (`desk`, BUILT): posture, the day strip and screen time
(docs/plans/r8-vision.md 2.1 rows 181, 182, 183; section 8; ROWS.md). Every case drives builder
C's real code on synthetic data (tests/r8_fakes_c.py: bodies built from joint angles, never a
real person's) and a fake ActivityWatch API; no network, no AI call:

- posture (181): >= 90 % of 60-s slouch or forward-head spans give a nudge, over three seeds;
  <= 1 false nudge per synthetic hour of good posture; at most 3 nudges in any hour; the
  workbook's "slouch 10 min -> a nudge"; the rule's own share of one core <= 10 % at 2 frames a
  second; its tally fits PostureTally;
- activity (182): a synthetic 8-hour day labelled right for >= 90 % of its minutes; only kind,
  start and end kept; the day strip joins it and finds the longest sitting stretch;
- screen time (183): per-program minutes and active time exact; no window title in the answer;
  no ActivityWatch -> "not_installed" (Vitals: "off until ActivityWatch is installed");
- cross-cutting: no point, box or picture in any report or tally; every view passes the
  not-medical scan (jarvis.coach.words.medical_hits).

Negative controls (each must make its case fail, or the suite proves nothing):
  no_hold          the posture rule's hold is an hour (`HOLD_S` 3600): held slouches never nudge
  all_phone        the activity rule calls any minute in view "phone" (`VOTE_SHARE` 0)
  titles_kept      the ActivityWatch reader names a program by its window title
  points_in_view   the posture view carries the body's points

    python evals/r8/desk.py      (standalone; R8's runner imports `cases` and `control`)
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / "src", ROOT / "tests"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import httpx  # noqa: E402
from r8_fakes_c import frames  # noqa: E402

from jarvis.coach import day as day_mod  # noqa: E402
from jarvis.coach.home import activity as A  # noqa: E402
from jarvis.coach.home import posture as P  # noqa: E402
from jarvis.coach.usecases import parse_tally  # noqa: E402
from jarvis.coach.words import medical_hits  # noqa: E402
from jarvis.homebridge import activitywatch as AW  # noqa: E402
from jarvis.homebridge.plugins import BridgeContext  # noqa: E402

PART = "desk"
BUILT = True
IST = ZoneInfo("Asia/Kolkata")
NINE = int(datetime(2026, 11, 26, 9, 0, tzinfo=IST).timestamp())
CALIB = [("upright", 15.0)]
POINT_KEYS = ('"x"', '"y"', '"z"', '"visibility"', '"points"', '"box"')
WORKDAY: list[tuple[str, float]] = [
    ("desk", 85 * 60), ("phone", 7 * 60), ("slouch", 8 * 60), ("desk", 40 * 60),
    ("eating", 25 * 60), ("away", 45 * 60), ("desk", 70 * 60), ("phone", 3 * 60),
    ("hidden", 2 * 60), ("desk", 30 * 60), ("away", 12 * 60), ("forward", 6 * 60),
    ("desk", 80 * 60), ("eating", 12 * 60), ("phone", 5 * 60), ("desk", 50 * 60),
]  # fmt: skip
VIEWS: list[dict[str, Any]] = []  # every view a case produced (the not-medical case reads them)


def _case(name: str, failures: list[str]) -> dict[str, Any]:
    return {"id": f"{PART}:{name}", "passed": not failures, "failures": failures}


def _posture(blocks: list[tuple[str, float]], seed: int = 7) -> tuple[P.PostureState, list[int]]:
    coach, state = P.PostureCoach(aspect=1.0), None
    tips: set[int] = set()
    for i, (_, _, results) in enumerate(frames(blocks, seed=seed)):
        for r in results:
            if r["task"] == "pose":
                state = coach.on_result(r, state)
        if state is None or not (state.nudged or i % 60 == 0):
            continue  # a view is read when a span asked for its nudge, and once a minute
        view = coach.summary(state)["view"]
        VIEWS.extend(view)
        tips.update(w["since"] for w in view if w["kind"] == "tip")
    assert state is not None
    return state, sorted(tips)


def posture_spans() -> list[str]:
    out = []
    for seed in (7, 19):
        blocks, spans = list(CALIB), 12
        for i in range(spans):
            kind = "slouch" if i % 2 else "forward"
            blocks += [("upright", 1250.0), (kind, 65.0 + (i % 5) * 14)]
        _, tips = _posture(blocks, seed)
        if len(tips) < 0.9 * spans:
            out.append(f"seed {seed}: {len(tips)} nudges for {spans} held spans")
    return out


def posture_false() -> list[str]:
    hour: list[tuple[str, float]] = []
    for i in range(12):
        hour += [
            ("upright", 240.0),
            ("lean" if i % 3 else "hidden", 25.0 + i),
            ("upright", 35.0 - i),
        ]
    out = []
    for seed in (3, 11):
        _, tips = _posture(CALIB + hour * 3, seed)
        if len(tips) > 3:
            out.append(f"seed {seed}: {len(tips)} nudges in 3 hours of good posture")
    return out


def posture_cap() -> list[str]:
    _, tips = _posture(CALIB + [("slouch", 70.0), ("upright", 20.0)] * 80)
    worst = max((sum(1 for b in tips if a <= b < a + 3600) for a in tips), default=0)
    return (
        [] if tips and worst <= P.PER_HOUR else [f"{worst} nudges in one hour ({len(tips)} in all)"]
    )


def posture_ten_minutes() -> list[str]:
    state, tips = _posture(CALIB + [("upright", 300.0), ("slouch", 600.0)])
    tally = parse_tally("posture", P.PostureCoach(aspect=1.0).summary(state)["tally"])
    out = [] if len(tips) == 1 else [f"{len(tips)} nudges for one 10-minute slouch"]
    if tally is None or not 540 <= getattr(tally, "slouch_seconds", 0) <= 620:
        out.append("the kept tally doesn't hold the slouch's ten minutes")
    return out


def posture_cost() -> list[str]:
    results = [r for _, _, rs in frames(CALIB + [("upright", 900.0), ("slouch", 900.0)])
               for r in rs if r["task"] == "pose"]  # fmt: skip
    coach, state = P.PostureCoach(aspect=1.0), None
    began = time.perf_counter()
    for r in results:
        state = coach.on_result(r, state)
        coach.summary(state)
    share = (time.perf_counter() - began) / len(results) * P.SUSPECT_RATE
    return [] if share <= 0.1 else [f"{share:.1%} of one core at 2 frames a second"]


def _activity(
    blocks: list[tuple[str, float]], seed: int = 7
) -> tuple[dict[str, Any], dict[int, str]]:
    coach, state = A.ActivityCoach(), None
    truth: dict[int, Counter[str]] = {}
    for t, kind, results in frames(blocks, start=NINE, seed=seed):
        truth.setdefault(int(t) // 60, Counter())[kind] += 1
        for r in results:
            state = coach.on_result(r, state)
    out = coach.summary(state)
    VIEWS.extend(out["view"])
    return out, {m: c.most_common(1)[0][0] for m, c in truth.items()}


def activity_day() -> list[str]:
    out = []
    for seed in (7, 23):
        got, truth = _activity(WORKDAY, seed)
        labels: dict[int, str] = {}
        for s in (got["tally"] or {}).get("segments", []):
            for m in range(s["start"] // 60, s["end"] // 60):
                labels[m] = s["kind"]
        right = sum(1 for m, k in truth.items() if labels.get(m) == k) / max(1, len(truth))
        if right < 0.9:
            out.append(f"seed {seed}: {right:.1%} of minutes right")
    return out


def activity_kept() -> list[str]:
    got, _ = _activity(WORKDAY[:6])
    tally = got["tally"] or {}
    out = []
    if parse_tally("activity", tally) is None:
        out.append("the tally doesn't fit ActivityTally")
    if any(set(s) != {"kind", "start", "end"} for s in tally.get("segments", [])):
        out.append("a segment keeps more than kind, start and end")
    item = {"use": "activity", "who": "me", "kept_at": "2026-11-26T10:00:00", "tally": tally}
    strip = day_mod.strip([item], date(2026, 11, 26), IST)
    if strip.longest is None or not strip.totals or strip.totals["desk"] < 3600:
        out.append("the day strip didn't join the kept tally")
    return out


WIN, AFK = "aw-watcher-window_LAPTOP", "aw-watcher-afk_LAPTOP"
TITLE = "Salary slip 2026 - Private bank page"


def _iso(hhmm: str) -> str:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(2026, 11, 26, h, m, tzinfo=IST).astimezone(UTC).isoformat()


def _aw(mode: str = "ok") -> Callable[[httpx.Request], httpx.Response]:
    win = [
        {
            "timestamp": _iso("09:00"),
            "duration": 3600,
            "data": {"app": "chrome.exe", "title": TITLE},
        },
        {"timestamp": _iso("10:00"), "duration": 1800, "data": {"app": "Code.exe", "title": "x"}},
    ]
    afk = [{"timestamp": _iso("09:00"), "duration": 4800, "data": {"status": "not-afk"}}]

    def answer(request: httpx.Request) -> httpx.Response:
        if mode == "down":
            raise httpx.ConnectError("refused", request=request)
        path = request.url.raw_path.decode().split("?")[0]
        buckets = {WIN: {"type": "currentwindow"}, AFK: {"type": "afkstatus"}}
        body: Any = {
            "/api/0/buckets/": buckets,
            f"/api/0/buckets/{WIN}/events": win,
            f"/api/0/buckets/{AFK}/events": afk,
        }.get(path)
        return httpx.Response(200 if body is not None else 404, json=body or {})

    return answer


async def _screen(mode: str = "ok") -> dict[str, Any]:
    ctx = BridgeContext(env={}, data_dir=Path("/tmp"), events=None)  # type: ignore[arg-type,unused-ignore]
    client = httpx.AsyncClient(transport=httpx.MockTransport(_aw(mode)))
    plugin = AW.ActivityWatchPlugin(ctx, client=client)
    try:
        (route,) = plugin.routes()
        got: dict[str, Any] = await route.handler({"day": "2026-11-26", "offset": "330"}, None)
        return got
    finally:
        await plugin.aclose()


async def screen_exact() -> list[str]:
    got = await _screen()
    programs = [{"name": "chrome", "minutes": 60.0}, {"name": "Code", "minutes": 20.0}]
    want = {"state": "ok", "day": "2026-11-26", "active_minutes": 80.0, "programs": programs}
    out = [] if got == want else [f"got {json.dumps(got)}"]
    if TITLE in json.dumps(got):
        out.append("a window title left the laptop")
    return out


async def screen_off() -> list[str]:
    got = await _screen("down")
    return [] if got == {"state": "not_installed"} else [f"no ActivityWatch answered {got}"]


def no_point() -> list[str]:
    flat = json.dumps(VIEWS)
    return [f"a view holds {k}" for k in POINT_KEYS if k in flat]


def not_medical() -> list[str]:
    said = [str(v) for w in VIEWS for v in w.values() if isinstance(v, str)]
    return [f"{line!r}: {hits}" for line in said if (hits := medical_hits(line))]


async def _run() -> list[dict[str, Any]]:
    VIEWS.clear()
    out = [
        _case("posture_spans", posture_spans()),
        _case("posture_false", posture_false()),
        _case("posture_cap", posture_cap()),
        _case("posture_ten_minutes", posture_ten_minutes()),
        _case("posture_cost", posture_cost()),
        _case("activity_day", activity_day()),
        _case("activity_kept", activity_kept()),
        _case("screen_exact", await screen_exact()),
        _case("screen_off", await screen_off()),
    ]
    return [*out, _case("no_point", no_point()), _case("not_medical", not_medical())]


async def cases() -> list[dict[str, Any]]:
    return await _run()


@contextmanager
def _swap(module: Any, attr: str, value: Any) -> Iterator[None]:
    old = getattr(module, attr)
    setattr(module, attr, value)
    try:
        yield
    finally:
        setattr(module, attr, old)


def _title_program(raw: object) -> str:
    return "Salary slip 2026 - Private bank page"  # the control: a window title as the name


def _points_view(s: P.PostureState) -> list[dict[str, Any]]:
    return [{"kind": "line", "text": P.UPRIGHT, "x": 0.5, "y": 0.4}]  # the control: a point leaks


CONTROLS: dict[str, tuple[Any, str, Any, str]] = {
    "no_hold": (P, "HOLD_S", 3600.0, f"{PART}:posture_spans"),
    "all_phone": (A, "VOTE_SHARE", 0.0, f"{PART}:activity_day"),
    "titles_kept": (AW, "program", _title_program, f"{PART}:screen_exact"),
    "points_in_view": (P, "_view", _points_view, f"{PART}:no_point"),
}


async def control() -> dict[str, Any]:
    failed: list[str] = []
    every = True
    for name, (module, attr, value, target) in CONTROLS.items():
        with _swap(module, attr, value):
            got = [r["id"] for r in await _run() if not r["passed"]]
        failed += [f"{name} -> {case}" for case in got]
        every = every and target in got
    return {
        "name": "desk: no hold; every minute a phone; titles kept; points in the view",
        "suite_failed": every,
        "failed_cases": failed,
    }


def main() -> int:
    results = asyncio.run(cases())
    ctl = asyncio.run(control())
    for r in results:
        print(("PASS " if r["passed"] else "FAIL ") + r["id"], *r["failures"])  # noqa: T201
    print("control:", "every control failed its case" if ctl["suite_failed"] else ctl)  # noqa: T201
    return 0 if all(r["passed"] for r in results) and ctl["suite_failed"] else 1


if __name__ == "__main__":
    sys.exit(main())
