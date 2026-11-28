# tests/test_r8_a_engine.py -- R8 builder A, row 216 (docs/plans/r8-vision.md 2.1, 4.2, 4.8, D4,
# D6, D7, D9; ROWS.md: "A rep count runs with the Wi-Fi off."). The engine's three R8 task bodies
# (console-vision-r8.js) and the setup test (console-vision-check.js), run in Node by
# tests/fixtures/r8/engine.mjs: the real console-vision.js with a fake MediaPipe, a fake browser
# whose canvases hold real pixels, FAKE model files served from /static/vendor/vision/<release>/
# and the module's SUMS8 block filled with their sums. Nothing here is a real model or a person.
from __future__ import annotations

from typing import Any

import pytest
from r8_fakes import FIXTURES, run_node

from jarvis.vision.results import OBJECT_LABELS, parse_result

ENGINE = FIXTURES / "engine.mjs"
NOT_INSTALLED = "not installed"
NO_LOAD = "The vision tools could not load. Check the connection and try again."


def scenario(name: str, **given: Any) -> Any:
    return run_node(ENGINE, f"mod.{name}", given)


def bodies(result: dict[str, Any]) -> list[dict[str, Any]]:
    return list(result["data"].get("bodies", []))


# ---- each loads only JARVIS-served, hash-checked files (row 216) ---------------------------------
def test_each_task_loads_only_its_pinned_files_from_jarvis() -> None:
    out = scenario("loads")
    assert {t: out["out"][t]["ok"] for t in ("pose", "hands", "digits")} == dict.fromkeys(
        ("pose", "hands", "digits"), True
    )
    assert out["fetches"] == [
        "/static/vendor/vision/r7-1/pose_landmarker_lite.task",  # lite: the browser's default
        "/static/vendor/vision/r8-1/hand_landmarker.task",
    ]  # the digits reader fetches nothing
    pose, hands = out["created"]
    assert pose["opts"]["numPoses"] == 4 and pose["opts"]["runningMode"] == "VIDEO"
    assert hands["opts"]["numHands"] == 2 and hands["opts"]["runningMode"] == "VIDEO"
    for made in out["created"]:
        assert made["opts"]["baseOptions"] == {"delegate": "CPU"}
        assert set(made["files"].values()) <= {
            "/static/vendor/vision/r7-1/vision_wasm_internal.js",
            "/static/vendor/vision/r7-1/vision_wasm_internal.wasm",
        }
    tasks = {t["id"]: t for t in out["tasks"]}
    assert tasks["pose"]["v"] == 2 and tasks["hands"]["v"] == 1 and tasks["digits"]["v"] == 1


def test_a_model_whose_bytes_differ_from_its_pin_is_not_installed() -> None:
    out = scenario("loads", files={"r8-1/hand_landmarker.task": "a tampered hand model"})
    assert out["out"]["hands"] == {"ran": False, "error": NOT_INSTALLED}
    assert out["out"]["pose"]["ok"] is True  # the other files still load
    unpinned = scenario("loads", sums={"r7-1/pose_landmarker_lite.task": ""})
    assert unpinned["out"]["pose"] == {"ran": False, "error": NOT_INSTALLED}  # no sum: never used
    missing = scenario("loads", files={"r8-1/hand_landmarker.task": None})
    assert missing["out"]["hands"]["error"] == NOT_INSTALLED  # not arrived yet (404)
    broken = scenario("loads", status=500)
    assert broken["out"]["pose"]["error"] == NO_LOAD and broken["out"]["hands"]["error"] == NO_LOAD


# ---- pose v2: everyone in view, a track per body (D6) --------------------------------------------
def test_each_body_keeps_its_track_as_two_people_cross() -> None:
    out = scenario("poseFrames", script="crossing", frames=24)
    for r in out["results"]:
        assert r["ok"] is True and parse_result(r) is not None  # the server's own contract
        by_track = {b["track"]: b["points"][23]["x"] for b in bodies(r)}
        assert set(by_track) == {0, 1}
    adult = [next(b for b in bodies(r) if b["track"] == 0) for r in out["results"]]
    hips = [b["points"][23]["x"] for b in adult]
    assert hips == sorted(hips) and hips[0] < 0.3 < 0.7 < hips[-1]  # track 0: the adult walking
    # right, before, during and after the crossing (the child walks left, smaller and behind)
    assert all(b["who"] == "" for r in out["results"] for b in bodies(r))  # no face matched here
    stamps = out["stamps"]
    assert all(b > a for a, b in zip(stamps, stamps[1:], strict=False))  # VIDEO mode's clock


def test_a_track_let_go_is_not_handed_to_the_next_person_at_once() -> None:
    out = scenario("poseFrames", script="leave-enter", frames=40)
    tracks = [sorted(b["track"] for b in bodies(r)) for r in out["results"]]
    assert tracks[0] == [0, 1] and tracks[4] == [0, 1]
    assert all(t == [0] for t in tracks[5:30])  # the second person left
    assert all(t == [0, 2] for t in tracks[30:])  # the newcomer is someone else: track 2, not 1


def test_at_most_four_bodies_and_every_point_inside_the_contract() -> None:
    five = scenario("poseFrames", script="five", frames=2)["results"]
    assert all(len(bodies(r)) == 4 and r["ok"] for r in five)
    wild = scenario("poseFrames", script="wild", frames=1)["results"][0]
    assert wild["ok"] is True and parse_result(wild) is not None
    (body,) = bodies(wild)  # the landmarker's short answer (20 points) is left out
    assert len(body["points"]) == 33
    for p in body["points"]:
        assert -1 <= p["x"] <= 2 and -10 <= p["z"] <= 10 and 0 <= p["visibility"] <= 1


# ---- hands v1 ------------------------------------------------------------------------------------
def test_hands_are_the_subjects_own_and_only_whole_ones() -> None:
    frames = [
        [{"side": "Left", "score": 0.9}, {"side": "Right", "score": 0.8}],
        [{"side": "Left", "score": 0.9, "points": 20}],  # not all 21 points: left out
        [{"side": "Both", "score": 0.9}],  # no known side: left out
    ]
    out = scenario("handsFrames", frames=frames)["results"]
    assert [[h["side"] for h in r["data"]["hands"]] for r in out] == [["left", "right"], [], []]
    assert all(r["ok"] and parse_result(r) is not None for r in out)
    assert all(len(h["points"]) == 21 for h in out[0]["data"]["hands"])
    mirrored = scenario("handsFrames", frames=frames[:1], mirrored=True)["results"][0]
    assert [h["side"] for h in mirrored["data"]["hands"]] == ["right", "left"]


# ---- row 216's own check: a rep count runs with the Wi-Fi off ------------------------------------
def test_a_rep_count_runs_with_the_wifi_off() -> None:
    out = scenario("repsOffline", reps=10)
    assert out["errors"] == [] and out["count"] == 10
    assert out["fetched_offline"] == 0  # nothing was asked of the network during the look
    assert out["view"] == [{"kind": "big", "n": 10, "word": "reps"}] and out["who"] == "me"


# ---- the setup test: frames a second and the share of one core (row 216, 4.8, D4) ---------------
def test_the_setup_test_reports_frames_a_second_and_the_share_of_one_core() -> None:
    out = scenario("setupTest", tasks=["pose", "hands"], opts={"seconds": 1})
    r = out["result"]
    assert out["error"] == "" and out["sent"] == 0  # nothing recorded or sent
    assert 10 <= r["fps"] <= 16 and r["model"] == "lite"
    for t in ("pose", "hands"):
        task = r["tasks"][t]
        assert task["n"] >= 10 and task["ms"] >= 0
        assert abs(task["core"] - task["fps"] * task["ms"] / 1000) < 0.01
    assert abs(r["core"] - sum(r["tasks"][t]["core"] for t in ("pose", "hands"))) < 0.002


def test_the_full_pose_model_is_kept_only_where_it_keeps_15_a_second() -> None:
    full = {"seconds": 1, "model": "full"}
    slow = scenario("setupTest", opts=full, slow={"FAKE pose full model": 60})
    assert slow["result"]["model"] == "lite"  # 60 ms a frame: the engine would slow itself
    assert slow["created"] == ["FAKE pose full model", "FAKE pose lite model"]
    fast = scenario("setupTest", opts=full, slow={"FAKE pose full model": 5})
    assert fast["result"]["model"] == "full" and fast["created"] == ["FAKE pose full model"]
    absent = scenario("setupTest", opts=full, files={"r8-1/pose_landmarker_full.task": None})
    assert absent["result"]["model"] == "lite"  # the full model has not arrived: lite, no error


def test_the_setup_test_needs_a_camera_a_tap_started_and_stops_with_it() -> None:
    assert scenario("setupTest", live=False)["error"] == "The camera starts only from a tap."
    stopped = scenario("setupTest", opts={"seconds": 3}, stopAfter=400)
    assert stopped["error"] == "The camera was stopped." and stopped["result"] is None
    assert scenario("setupTest", tasks=["embed"])["error"] == "Pick a vision task to test."


# ---- digits v1 (D7): the monitor held up to the webcam ------------------------------------------
def test_digits_reads_a_monitor_framed_in_a_webcam_picture() -> None:
    frame = {"fw": 1280, "fh": 720, "fx": 500, "fy": 200}
    box = {"x": 0.36, "y": 0.24, "w": 0.24, "h": 0.4}
    out = scenario("digitsFrame", values=[128, 82, 71], frame=frame, box=box)
    r = out["result"]
    assert r["ok"] is True and parse_result(r) is not None and out["fetches"] == 0
    assert [(line["value"], line["score"] >= 0.8) for line in r["data"]["lines"]] == [
        (128, True),
        (82, True),
        (71, True),
    ]


def test_a_canvas_that_changes_pixels_makes_digits_not_installed() -> None:
    assert scenario("digitsFrame", canvas="blank")["error"] == NOT_INSTALLED  # its self-check
    assert scenario("digitsFrame", canvas="none")["error"] == NOT_INSTALLED  # no ImageData


@pytest.mark.parametrize(
    ("given", "right_min", "wrong_max"),
    [
        ({"n": 100, "plain": True, "seed": 7}, 92, 0),  # the plain LCD (94 measured)
        ({"n": 120, "seed": 11}, 104, 2),  # every kind: slant, turn, blur, ghosts, LED ...
        ({"n": 100, "seed": 5}, 81, 3),  # 83 measured
    ],
)
def test_the_reader_on_synthetic_displays(
    given: dict[str, Any], right_min: int, wrong_max: int
) -> None:
    out = scenario("accuracy", **given)
    assert out["right"] >= right_min, out["misses"][:3]  # all three lines right, each sure (0.8)
    assert out["sure_wrong"] <= wrong_max  # a sure wrong line (he confirms or corrects every read)


def test_the_readers_controls_fail() -> None:
    assert scenario("accuracy", n=30, plain=True, mutate="last-digit")["right"] == 0
    honest = scenario("accuracy", n=60, seed=5)["sure_wrong"]
    assert scenario("accuracy", n=60, seed=5, mutate="all-sure")["sure_wrong"] > honest  # doubts


@pytest.mark.parametrize("seed", [41, 42])
def test_262_monitor_screens_read_right_on_95_percent_and_never_wrong(seed: int) -> None:
    """Builder D's bar (its screens on r8-d, mirrored here): through the pane's own rule a wrong
    reading is worse than none, so a line not read surely is refused and he types it instead."""
    out = scenario("monitors", n=240, seed=seed)
    assert out["right"] / out["n"] >= 0.95, out["misses"]
    assert out["wrong"] == 0, out["misses"]


def test_262_the_monitor_control_fails() -> None:
    assert scenario("monitors", n=40, seed=41, mutate="last-digit")["wrong"] > 30


def test_a_display_whose_lines_lack_a_top_and_bottom_is_never_sure() -> None:
    lines = run_node("console-vision-r8.js", "mod.readDisplay", [], 0, 0)
    assert lines == []  # nothing to read
    digit = run_node("console-vision-r8.js", "mod.nearest", [1, 1, 1, 1, 1, 1, 0])
    assert digit["digit"] == 0 and digit["score"] == 1
    doubt = run_node("console-vision-r8.js", "mod.nearest", [1, 1, 1, 1, 1, 1, 0.4])
    assert doubt["score"] < 0.8  # an 8 or a 0: not sure


# ---- D9's fallback: SSD-MobileNet v1's COCO ids as the engine's labels ---------------------------
def test_the_coco_ids_give_exactly_the_engines_80_labels() -> None:
    out = scenario("coco")
    assert tuple(out["labels"]) == OBJECT_LABELS and len(out["ids"]) == 80
    assert not {12, 26, 29, 30, 45, 66, 68, 69, 71, 83} & set(out["ids"])
    # ids 47 cup, 12 (unused), 44 bottle at 0.4 (too low), 1 person, 90 toothbrush; the best two
    assert out["decoded"] == [
        {"label": "cup", "score": 0.9, "box": {"x": 0.2, "y": 0.1, "w": 0.4, "h": 0.4}},
        {"label": "person", "score": 0.7, "box": {"x": 0.1, "y": 0, "w": 0.4, "h": 1}},
    ]  # a box outside the frame is held inside it
