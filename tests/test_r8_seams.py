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

from jarvis.vision.results import BODIES_MAX, HAND_POINTS, POSE_POINTS, TASKS, parse_result

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
def test_hands_and_digits_join_the_kept_tasks() -> None:
    assert TASKS == ("text", "code", "objects", "pose", "quality", "hands", "digits")
    assert HAND_POINTS == 21 and POSE_POINTS == 33 and BODIES_MAX == 4


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


def _bodies(*who: str) -> list[dict[str, Any]]:
    return [{"track": n, "who": w, "points": _body()} for n, w in enumerate(who)]


def test_pose_v2_carries_everyone_in_view_with_a_track_and_who() -> None:
    # the owner's D6: everyone in view by default; `who` is "", "me" or a consented fp_ id
    four = _result("pose", {"bodies": _bodies("me", "fp_0123456789ab", "", "")})
    assert parse_result(four) is not None
    assert parse_result(_result("pose", {"bodies": []})) is not None  # nobody in view
    assert parse_result(_result("pose", {"points": _body()})) is not None  # R7's v1 still fits
    for bad in (
        {"bodies": _bodies("", "", "", "", "")},  # at most four bodies
        {"bodies": _bodies("Shruti")},  # never a name
        {"bodies": [{"track": 0, "who": "", "points": _body()}] * 2},  # one track, one body
        {"bodies": [{"track": True, "who": "", "points": _body()}]},
        {"bodies": [{"track": 64, "who": "", "points": _body()}]},
        {"bodies": _bodies("me"), "points": _body()},  # v1 or v2, never both
        {"bodies": [{**_bodies("")[0], "face": [0.1, 0.2]}]},  # nothing rides along
        {"points": _body(66)},
    ):
        assert parse_result(_result("pose", bad)) is None, bad


def test_digits_are_a_displays_lines_and_nothing_else() -> None:
    reading = {"lines": [{"value": 128, "score": 0.97}, {"value": 82, "score": 0.95},
                         {"value": 71, "score": 0.9}]}  # fmt: skip
    assert parse_result(_result("digits", reading)) is not None
    for bad in (
        {"lines": [{"value": 1000, "score": 0.9}]},
        {"lines": [{"value": 12.5, "score": 0.9}]},
        {"lines": [{"value": 1, "score": 0.9}] * 5},
        {"lines": [{"value": 120, "score": 0.9, "label": "systolic"}]},
        {"lines": [], "text": "128/82"},
    ):
        assert parse_result(_result("digits", bad)) is None, bad


# ---- S15 · the posture nudge kind and its caps ------------------------------------------------------
def test_the_posture_nudge_is_one_new_kind_in_every_table() -> None:
    from typing import get_args

    from jarvis.alerts import R8_ALERT_KINDS, AlertKind
    from jarvis.buildbook.plain import ALERT_WORDS
    from jarvis.helpers import kinds
    from jarvis.helpers.nudges.models import DEFAULTS, LABEL, kind_of
    from jarvis.helpers.nudges.words import describe
    from jarvis.notify.policy import DAYTIME_RING_KINDS, EPHEMERAL_KINDS
    from jarvis.notify.ports import DEFAULT_URGENCY
    from jarvis.notify.storm import NUDGE_KINDS
    from jarvis.webpush.service import TARGETS

    assert R8_ALERT_KINDS == ("nudge_posture",) and "nudge_posture" in get_args(AlertKind)
    assert "nudge_posture" in kinds.NUDGE_KINDS and "nudge_posture" in kinds.KINDS_OF["nudges"]
    assert kinds.DEFAULT_CAPS["nudge_posture"] == kinds.POSTURE_PER_DAY == 8
    assert kinds.POSTURE_PER_HOUR == 3
    assert DEFAULTS["nudge_posture"].on is False  # off until he switches it on
    assert DEFAULT_URGENCY["nudge_posture"] == "important"
    assert "nudge_posture" in DAYTIME_RING_KINDS and "nudge_posture" in EPHEMERAL_KINDS
    assert "nudge_posture" in NUDGE_KINDS and "nudge_posture" in TARGETS
    assert "nudge_posture" in ALERT_WORDS and LABEL["nudge_posture"] == "Sit up straight"
    assert kind_of("posture") == kind_of("slouching") == "nudge_posture"
    line = describe("nudge_posture", DEFAULTS["nudge_posture"])
    assert line.startswith("Sit up straight: off") and "at most 3 an hour" in line
    js = (STATIC / "console-alerts.js").read_text(encoding="utf-8")
    assert "['nudge_posture', " in js
