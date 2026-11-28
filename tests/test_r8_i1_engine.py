# tests/test_r8_i1_engine.py -- R8 I1 join (docs/plans/r8-integration/I1-NOTES.md): the engine
# items joined across the builders and asked by R8.1's builder F through the coordinator:
#   - live(taskIds, {setup}) puts `setup` on every Result it hands its use cases (`r.setup`,
#     frozen once); without it a Result has no `setup`
#   - every Result carries the frame's `aspect` (width / height), in the browser and on the home
#     laptop; the shared geometry and the home rules scale x by it, so angles are true
#   - JarvisCamera.keepWhile(win): the small window on top keeps the camera while the tab is hidden
#   - D9: with EfficientDet not installed, `objects` runs on R13's SSD-MobileNet (cocoObjects)
#   - the setup test never starts or stops the camera; the Desk pane never posts camera health
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import pytest
import r8_j_fakes as F
from r7_fakes_b import STATIC, run_dom
from r8_fakes import run_node

from jarvis.coach.home import aspect_of
from jarvis.coach.home import runtime as R
from jarvis.coach.home.seated import near_side
from jarvis.home.ports import CoachState
from jarvis.vision.results import parse_result


def _driver(*steps: dict[str, Any]) -> dict[str, Any]:
    return run_dom("driver", steps=list(steps))


def _text(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


# ---- live()'s setup -----------------------------------------------------------------------------
ROUTINE = {"routine": "tai-chi-1", "rows": [{"t": i, "knee": 90 + i} for i in range(150)]}


def test_live_puts_its_setup_on_every_result_frozen_and_whole() -> None:
    out = _driver(
        {"op": "use", "id": "coach", "tasks": ["probe"]},
        {"op": "live", "tasks": ["probe"], "uses": ["coach"], "setup": ROUTINE},
        {"op": "wait", "ms": 250},
        {"op": "end"},
    )
    got = out["res"]["coach"]
    assert len(got) >= 2 and out["errors"] == []
    for r in got:
        assert r["has"] is True and r["frozen"] is True
        assert r["setup"] == ROUTINE  # all 150 rows: a routine is not cut at 100


def test_without_a_setup_a_result_has_none() -> None:
    out = _driver(
        {"op": "use", "id": "coach", "tasks": ["probe"]},
        {"op": "live", "tasks": ["probe"], "uses": ["coach"]},
        {"op": "wait", "ms": 200},
        {"op": "end"},
    )
    assert out["res"]["coach"] and all(r["has"] is False for r in out["res"]["coach"])


# ---- the frame's aspect -------------------------------------------------------------------------
def test_every_result_carries_the_frames_aspect() -> None:
    out = _driver(
        {"op": "use", "id": "coach", "tasks": ["probe"]},
        {"op": "live", "tasks": ["probe"], "uses": ["coach"]},
        {"op": "wait", "ms": 200},
        {"op": "end"},
    )
    assert {r["aspect"] for r in out["res"]["coach"]} == {round(64 / 48, 3)}  # the fake 64 x 48


def test_the_server_takes_an_aspect_in_range_only() -> None:
    q = {"light": 0.5, "sharp": 0.5}
    base = {"task": "quality", "v": 1, "at": 1764300000, "ms": 3, "device": "phone", "ok": True,
            "data": q, "quality": q}  # fmt: skip
    assert parse_result(base) is not None  # an older device without it still parses
    tall = parse_result({**base, "aspect": 9 / 16})
    assert tall is not None and tall.aspect == pytest.approx(0.5625)
    for bad in (0.0, 9.0, "wide", math.inf):
        assert parse_result({**base, "aspect": bad}) is None


def test_the_geometry_scales_x_by_the_aspect() -> None:
    a, b, c = {"x": 0.6, "y": 0.4}, {"x": 0.5, "y": 0.5}, {"x": 0.4, "y": 0.4}
    square = run_node("console-coach-geom.js", "mod.angle", a, b, c)
    wide = run_node("console-coach-geom.js", "mod.angle", a, b, c, 16 / 9)
    assert square == pytest.approx(90.0, abs=1e-6)
    assert wide == pytest.approx(2 * math.degrees(math.atan(0.1 * 16 / 9 / 0.1)), abs=1e-6)
    assert run_node("console-coach-geom.js", "mod.angle", a, b, c, 99) == pytest.approx(90.0)
    d = run_node("console-coach-geom.js", "mod.dist", {"x": 0.0, "y": 0.0}, {"x": 0.3, "y": 0.0}, 2)
    assert d == pytest.approx(0.6)


def test_the_home_rules_read_the_results_aspect() -> None:
    assert aspect_of({"aspect": 16 / 9}) == pytest.approx(16 / 9)
    assert aspect_of({}) == 1.0 and aspect_of({"aspect": True}) == 1.0
    assert aspect_of({"aspect": 40.0}, 1.5) == 1.5
    pts = [{"x": 0.25, "y": 0.5, "visibility": 0.99} for _ in range(33)]
    assert near_side(pts)[11] == (0.25, 0.5)
    assert near_side(pts, 2.0)[11] == (0.5, 0.5)


class _Aspects:
    """A home use case that only notes each Result's aspect."""

    id = "posture"
    tasks = ("pose",)

    def __init__(self) -> None:
        self.aspects: list[Any] = []

    def on_result(self, result: Any, state: Any) -> Any:
        self.aspects.append(result.get("aspect"))
        return {"n": 1}

    def summary(self, state: Any) -> dict[str, Any]:
        return {"view": [{"kind": "big", "n": 1, "word": "looks"}], "tally": None}


async def test_the_home_laptop_puts_the_streams_aspect_on_each_result() -> None:
    clock = F.FakeClock()
    src = F.FakeSource([[F.body(0.5)]], clock, fps=1.0)
    case = _Aspects()
    rt = R.HomeRuntime("desk_cam", src, F.FakePose(src), F.Sink(),
                       registry={"posture": lambda: case}, wall=clock.wall, mono=clock.mono,
                       idle_s=0.01, retry_s=0.01)  # fmt: skip
    rt.apply(CoachState(rev=1, uses={"desk_cam": ("posture",)}))
    for _ in range(3):
        await rt.step()
    assert case.aspects and set(case.aspects) == {640 / 360}  # the fake sub-stream, 640 x 360


def test_the_runtime_reads_the_one_rate_hook_name() -> None:
    from jarvis.coach.home.posture import PostureCoach

    assert callable(PostureCoach().wanted_rate)
    assert 'getattr(use.case, "wanted_rate", None)' in Path(R.__file__).read_text(encoding="utf-8")


# ---- the camera door: keepWhile ---------------------------------------------------------------
def _cam(*steps: dict[str, Any]) -> list[dict[str, Any]]:
    return list(run_dom("camera", steps=list(steps))["steps"])


def test_the_small_window_keeps_the_camera_while_the_tab_is_hidden() -> None:
    out = _cam({"op": "start", "tap": True}, {"op": "pip"}, {"op": "hideStay"},
               {"op": "pipClose"})  # fmt: skip
    start, pip, hidden, closed = out
    assert start["live"] and pip["ok"] is True
    assert hidden["live"] is True  # the tab is hidden, the small window is open: still on
    assert closed["live"] is False and closed["liveTracks"] == 0  # closing it stops the camera


def test_without_a_small_window_or_with_both_hidden_the_camera_stops() -> None:
    plain = _cam({"op": "start", "tap": True}, {"op": "hideStay"})
    assert plain[-1]["live"] is False
    locked = _cam({"op": "start", "tap": True}, {"op": "pip"}, {"op": "hideStay"},
                  {"op": "pipHide"})  # fmt: skip
    assert locked[2]["live"] is True and locked[3]["live"] is False  # screen locked: both hidden
    own = _cam({"op": "start", "tap": True}, {"op": "keepSelf"}, {"op": "hideStay"})
    assert own[-1]["live"] is False  # the page's own window keeps nothing


# ---- D9's objects fallback, the setup test and the Desk pane ------------------------------------
def test_objects_falls_back_to_the_vendored_ssd_only_when_efficientdet_is_not_installed() -> None:
    js = _text("console-vision.js")
    body = js[js.index("async function loadCoco()") : js.index("const qualityTask")]
    assert "open13('objects', PERSON_MODEL, CHECKS_AT_LOAD.person)" in body  # R13's file, its check
    assert "e.message !== NOT_INSTALLED) throw e" in body  # only a model that hasn't arrived
    assert "R8.cocoObjects(" in body and "OBJECT_LABELS.includes(x.label)" in body
    labels = run_node("console-vision-r8.js", "mod.cocoObjects", [1, 44, 77, 12],
                      [0.9, 0.8, 0.7, 0.9], [0.1, 0.1, 0.5, 0.5] * 4, 4, 0.5, 50)  # fmt: skip
    assert [o["label"] for o in labels] == ["person", "bottle", "cell_phone"]  # id 12 is unused


def test_the_setup_test_and_the_task_bodies_never_start_or_stop_the_camera() -> None:
    for name in ("console-vision-check.js", "console-vision-r8.js", "console-vision.js"):
        js = _text(name)
        assert not re.search(r"\b(?:C|cam|JarvisCamera)\s*\.\s*(?:start|stop|lock)\s*\(", js), name


def test_the_desk_pane_never_posts_camera_health_the_camera_door_does() -> None:
    assert "/v1/camera/health" not in _text("console-coach-desk.js")
    assert "/v1/camera/health" in _text("console-camera.js")


def test_the_desk_pane_keeps_the_camera_through_the_small_window() -> None:
    js = _text("console-coach-desk.js")
    assert "C.keepWhile(win)" in js and "unless the small window on top is open" in js
