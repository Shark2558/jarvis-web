# tests/test_r8_seams.py -- R8 I0 seams (docs/plans/r8-vision.md section 7.1, S1-S23), the
# server's half: the Result contract (`hands`, `pose` v2), the assets' `r8-1` release, the
# use-case registry and its tallies, the sealed coach stores, the Privacy rows, the routes, the
# brain's tool, the ports, the camera spots, the Vitals camera lines, the bridge's two routes,
# the posture nudge kind, the settings, the wiring slots and the version. The console's half is
# tests/test_r8_console_seams.py; the not-medical scan is tests/test_r8_not_medical.py.
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from jarvis.vision.results import HAND_POINTS, POSE_POINTS, TASKS, parse_result

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "jarvis"
STATIC = SRC / "api" / "static"


def _result(task: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "task": task,
        "v": 1,
        "at": 1764300000,
        "ms": 30,
        "device": "browser",
        "ok": True,
        "data": data,
        "quality": {"light": 0.5, "sharp": 0.5},
    }


def _hand(side: str = "left", n: int = HAND_POINTS, **point: float) -> dict[str, Any]:
    p = {"x": 0.4, "y": 0.5, "z": -0.02, **point}
    return {"side": side, "score": 0.93, "points": [dict(p) for _ in range(n)]}


def _body(n: int = POSE_POINTS) -> list[dict[str, float]]:
    return [{"x": 0.5, "y": 0.4, "z": -0.1, "visibility": 0.9} for _ in range(n)]


# ---- S1 · the Result contract: `hands` (v1) and `pose` v2 ---------------------------------------
def test_hands_is_a_sixth_task_and_the_wardrobe_four_stay_apart() -> None:
    assert TASKS == ("text", "code", "objects", "pose", "quality", "hands")
    assert HAND_POINTS == 21 and POSE_POINTS == 33


def test_a_hands_result_is_two_hands_of_21_points_at_most() -> None:
    two = _result("hands", {"hands": [_hand("left"), _hand("right")]})
    assert parse_result(two) is not None
    assert parse_result(_result("hands", {"hands": []})) is not None  # no hand in view
    for bad in (
        {"hands": [_hand(), _hand(), _hand()]},  # a third hand
        {"hands": [_hand(n=20)]},  # a hand is all 21 points or none
        {"hands": [_hand(n=22)]},
        {"hands": [_hand(side="both")]},
        {"hands": [_hand(x=3.0)]},  # outside the frame's range
        {"hands": [{**_hand(), "label": "Akash"}]},  # nothing else rides along
        {"hands": [_hand()], "box": [0, 0, 1, 1]},
        {"hands": [{**_hand(), "score": 1.5}]},
    ):
        assert parse_result(_result("hands", bad)) is None, bad


def test_pose_v2_carries_others_and_never_a_second_body() -> None:
    assert parse_result(_result("pose", {"points": _body(), "others": 1})) is not None
    assert parse_result(_result("pose", {"points": _body(), "others": 0})) is not None
    v1 = parse_result(_result("pose", {"points": _body()}))  # R7's v1 result still fits
    assert v1 is not None
    for bad in (
        {"points": _body(), "others": 2},  # 0 or 1: whether someone else is in view
        {"points": _body(), "others": -1},
        {"points": _body(), "others": True},
        {"points": _body(66)},  # a second body's points never reach a use case
        {"points": _body(), "others": 1, "other_points": _body()},
    ):
        assert parse_result(_result("pose", bad)) is None, bad
