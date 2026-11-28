# tests/test_r81_g_coaches.py -- R8.1 builder G: the dynamic coaches (docs/plans/r8-vision.md
# v8.0.4 section 2.2 rows 228, 230, 235, 237, 239; docs/plans/r8-integration/ROWS.md). Each row's
# acceptance test, on synthetic data only (never a real person's): the console's use cases
# (console-coach-<x>.js) run in Node on the scripted sessions of
# tests/fixtures/r8/dynamic_sequences.mjs, behind a stand-in for JarvisVision.use; the truth is
# computed there from the continuous script, never read from a module.
# A session's setup (the wall or spotter he confirms, the marks he taps, his stance) rides on every
# Result as `setup` -- S2's contract line from R8's join (live(..., {setup}) -> r.setup; the R8.1
# join moved this part from a first state {setup} to it). Without it, the handstand coach times
# nothing and the agility timer asks for its marks: the safe default.
# Every tally must fit its jarvis.coach.usecases model (a tally that doesn't is dropped), every
# view holds only the fixed widget kinds, and no view says anything medical.
from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

import pytest
from r7_fakes_b import use_case_problems
from r8_fakes import FIXTURES, STATIC, run_node

from jarvis.coach.usecases import BY_ID, TALLIES, VIEW_KINDS, parse_tally
from jarvis.coach.words import STOP, medical_hits

SEQ = FIXTURES / "dynamic_sequences.mjs"
MODULES = {
    "boxing": "console-coach-boxing.js",
    "agility": "console-coach-agility.js",
    "jump": "console-coach-jump.js",
    "handstand": "console-coach-handstand.js",
    "kettlebell": "console-coach-kettlebell.js",
}
WALL = {"support": "wall"}
ASK = "Confirm a wall behind you or a spotter with you first."


def node(call: str, *args: Any) -> Any:
    return run_node(SEQ, f"mod.{call}", *args)


def _texts(view: Iterable[dict[str, Any]]) -> list[str]:
    return [str(v) for w in view for k, v in w.items() if k != "kind" and isinstance(v, str)]


def _fits(use: str, tally: dict[str, Any] | None) -> None:
    assert tally is not None, use
    model = TALLIES[use]
    assert model is not None and parse_tally(use, tally) is not None, (use, tally)
    assert set(tally) == set(model.model_fields), use  # counts, times, scores, labels: no point


def _plain_view(use: str, view: list[dict[str, Any]]) -> None:
    assert view and len(view) <= 8, use
    assert {w["kind"] for w in view} <= set(VIEW_KINDS), use
    assert [t for t in _texts(view) if medical_hits(t)] == [], use
    assert STOP in _texts(view), use  # every session says it


def _per_20(truth: int) -> int:  # "within one per 20"
    return max(1, math.ceil(truth / 20))


# ---- the guard: each module is a use case on the tripod phone, registered once ----------------
@pytest.mark.parametrize("use, name", sorted(MODULES.items()))
def test_each_dynamic_coach_passes_the_use_case_guard_and_registers_once(
    use: str, name: str
) -> None:
    js = (STATIC / name).read_text(encoding="utf-8")
    assert js.isascii() and len(js.splitlines()) <= 200
    assert use_case_problems(js) == [], name
    assert js.count("JarvisVision.use(") == 1 and f"id: '{use}'" in js
    assert BY_ID[use].module == name and BY_ID[use].source == "phone" and BY_ID[use].health


@pytest.mark.parametrize("use, name", sorted(MODULES.items()))
def test_before_anything_happens_a_coach_keeps_nothing(use: str, name: str) -> None:
    out = node("emptySummary", name)
    assert out["tally"] is None
    _plain_view(use, out["view"])


# ---- row 228: shadowboxing --------------------------------------------------------------------
@pytest.mark.parametrize("fps", [30, 15])
def test_228_punch_counts_are_within_one_per_20(fps: int) -> None:
    for seed, lead, drops in ((1, "left", 0), (2, "right", 0), (3, "left", 11), (4, "right", 9)):
        out = node(
            "boxingSession", {"fps": fps, "seed": seed, "lead": lead, "punches": 60, "drops": drops}
        )
        truth = len(out["truth"])
        assert abs(out["tally"]["punches"] - truth) <= _per_20(truth), (fps, seed, out["tally"])
        got = node("matchPunches", out["seen"], out["truth"])
        assert got["missed"] <= _per_20(truth) and got["extra"] <= _per_20(truth), (fps, seed, got)
        _fits("boxing", out["tally"])
        _plain_view("boxing", out["view"])


def test_228_punch_types_are_right_on_85_percent_at_30_fps_and_not_about() -> None:
    same = total = 0
    for seed, lead in ((1, "left"), (2, "right"), (5, "left"), (6, "right")):
        out = node("boxingSession", {"fps": 30, "seed": seed, "lead": lead, "punches": 50})
        got = node("matchPunches", out["seen"], out["truth"])
        same, total = same + got["sameType"], total + len(out["truth"])
        assert out["tally"]["about"] is False
        assert out["tally"]["jabs"] and out["tally"]["crosses"]
        assert out["tally"]["hooks"] and out["tally"]["uppercuts"]
    assert same / total >= 0.85, (same, total)


def test_228_at_15_fps_the_counts_stand_and_the_types_are_marked_about() -> None:
    out = node("boxingSession", {"fps": 15, "seed": 7, "punches": 40})
    assert out["tally"]["about"] is True
    assert "Punch types are about right at this frame rate." in _texts(out["view"])
    assert abs(out["tally"]["punches"] - len(out["truth"])) <= _per_20(len(out["truth"]))


def test_228_combinations_are_read_and_each_punch_is_counted_soon_after_it_returns() -> None:
    out = node("boxingSession", {"fps": 30, "seed": 8, "punches": 60})
    right = sum(a == b for a, b in zip(out["combos"], out["combosSeen"], strict=True))
    assert right / len(out["combos"]) >= 0.85, (out["combos"], out["combosSeen"])
    assert out["view"][2]["text"].startswith("Last combination: ")
    lags = [s["at"] - t["end"] for s, t in zip(out["seen"], out["truth"], strict=False)]
    assert max(lags) <= 0.35, max(lags)  # the count comes as the hand gets back to its guard


def test_228_the_lead_hand_is_the_shoulder_nearer_the_camera_else_the_stance_he_set() -> None:
    southpaw = node("boxingSession", {"fps": 30, "seed": 2, "lead": "right", "punches": 30})
    level = node(
        "boxingSession",
        {"fps": 30, "seed": 2, "lead": "right", "turn": 0, "setup": {"stance": "southpaw"}},
    )
    for out in (southpaw, level):
        got = node("matchPunches", out["seen"], out["truth"])
        assert got["sameType"] / len(out["truth"]) >= 0.85


# ---- row 230: the agility timer between the marks he tapped -----------------------------------
@pytest.mark.parametrize("marks", ["line", "shuttle", "box"])
def test_230_split_times_are_within_0_2_s(marks: str) -> None:
    for fps, seed, drops in ((15, 1, 0), (15, 2, 7), (10, 3, 0)):
        out = node(
            "agilityRun",
            {"marks": marks, "fps": fps, "seed": seed, "runs": 3, "drops": drops, "noise": 0.004},
        )
        assert len(out["measured"]) == len(out["truth"]) == 3, (marks, fps)  # no crossing missed
        for run, truth in zip(out["measured"], out["truth"], strict=True):
            assert len(run) == len(truth)
            assert max(abs(a - b) for a, b in zip(run, truth, strict=True)) <= 0.2, (run, truth)
        tally = out["tally"]
        _fits("agility", tally)
        assert tally["splits"] == sum(len(r) for r in out["truth"])
        assert abs(tally["total_s"] - sum(sum(r) for r in out["truth"])) <= 0.3
        assert abs(tally["best_s"] - min(sum(r) for r in out["truth"])) <= 0.2
        _plain_view("agility", out["view"])


def test_230_a_skipped_mark_is_missed_and_that_run_is_not_the_best() -> None:
    out = node("agilityRun", {"marks": "box", "skip": [2], "runs": 1})
    assert out["missed"] == 1 and len(out["measured"]) == 1
    assert out["tally"]["best_s"] == 0  # a run with a missed mark is never the best
    clean = node("agilityRun", {"marks": "box", "runs": 1})
    assert clean["missed"] == 0 and clean["tally"]["best_s"] > 0


@pytest.mark.parametrize(
    "setup",
    [
        None,
        {"marks": [{"x": 0.2, "y": 0.9}]},  # one mark is not a drill
        {"marks": [{"x": 0.2, "y": 0.9}, {"x": 1.4, "y": 0.9}]},  # off the picture
        {"marks": "0.2,0.9;0.8,0.9"},
    ],
)
def test_230_without_two_good_marks_it_times_nothing_and_asks_for_them(setup: Any) -> None:
    out = node("agilityRun", {"setupOverride": setup, "runs": 1})
    assert out["tally"] is None and out["measured"] == []
    assert out["view"][0] == {
        "kind": "paused",
        "why": "Tap the marks on the screen first, in the order you will run them.",
    }


# ---- row 235: jump height and landing ---------------------------------------------------------
HEIGHTS = [0.08, 0.15, 0.22, 0.3, 0.38, 0.45, 0.55]


def test_235_height_from_flight_time_is_within_5_cm_at_30_fps() -> None:
    for seed, phase in ((1, 0.013), (2, 0.021), (3, 0.002)):
        out = node("jumpSession", {"fps": 30, "seed": seed, "heights": HEIGHTS, "phase": phase})
        assert len(out["seen"]) == len(HEIGHTS)  # every jump counted
        for got, truth in zip(out["seen"], out["truth"], strict=True):
            assert abs(got["cm"] - truth["cm"]) <= 5, (seed, got, truth)
        assert out["tally"]["about"] is False and out["view"][0]["word"] == "cm"
        _fits("jump", out["tally"])
        _plain_view("jump", out["view"])


def test_235_at_15_fps_it_is_within_10_cm_and_shown_as_about() -> None:
    for seed, phase in ((4, 0.031), (5, 0.047), (6, 0.005)):
        out = node("jumpSession", {"fps": 15, "seed": seed, "heights": HEIGHTS, "phase": phase})
        assert len(out["seen"]) == len(HEIGHTS)
        for got, truth in zip(out["seen"], out["truth"], strict=True):
            assert abs(got["cm"] - truth["cm"]) <= 10, (seed, got, truth)
        assert out["tally"]["about"] is True and out["view"][0]["word"] == "cm, about"
        assert "Heights are about right at this frame rate." in _texts(out["view"])


def test_235_one_foot_lifted_is_not_a_jump() -> None:
    out = node("jumpSession", {"heights": [0.3, 0.2], "footLift": 0.2})
    assert out["tally"]["jumps"] == 2


def test_235_stiff_and_knees_in_landings_are_flagged_on_90_percent_and_soft_ones_never() -> None:
    kinds = ["soft", "stiff", "in", "stiff", "soft", "in", "in", "stiff", "soft", "stiff", "in"]
    flagged = {"stiff": 0, "in": 0}
    false = 0
    for seed, fps in ((1, 30), (2, 15), (3, 30)):
        heights = [0.2 + 0.02 * i for i in range(len(kinds))]
        out = node("jumpSession", {"fps": fps, "seed": seed, "heights": heights, "landings": kinds})
        for got, truth in zip(out["seen"], out["truth"], strict=True):
            if truth["kind"] == "stiff":
                flagged["stiff"] += got["stiff"]
            elif truth["kind"] == "in":
                flagged["in"] += got["kneesIn"]
            false += truth["kind"] == "soft" and (got["stiff"] or got["kneesIn"])
            false += truth["kind"] == "in" and got["stiff"]
        assert out["tally"]["stiff"] + out["tally"]["knees_in"] >= 1
    assert flagged["stiff"] / (3 * kinds.count("stiff")) >= 0.9
    assert flagged["in"] / (3 * kinds.count("in")) >= 0.9
    assert false == 0


# ---- row 237: the handstand: never without a wall or a spotter --------------------------------
@pytest.mark.parametrize(
    "setup",
    [None, {}, {"support": ""}, {"support": "nobody"}, {"support": "WALL"}, {"limit": 0.3}],
)
def test_237_handstand_cannot_start_without_a_wall_or_a_spotter(setup: Any) -> None:
    out = node("handstandSession", {"holds": [15, 25], "setup": setup})
    assert out["tally"] is None and out["holds"] == 0 and out["best"] == 0
    assert [w["kind"] for w in out["view"]] == ["paused", "line"]
    assert out["view"][0]["why"] == ASK
    assert not any(w["kind"] == "timer" for w in out["view"])


def test_237_upside_down_without_support_it_says_come_down() -> None:
    out = node("handstandSession", {"holds": [15], "viewAt": 8})
    assert out["mid"][0] == {
        "kind": "paused",
        "why": "Come down now. Confirm a wall or a spotter first.",
    }
    assert out["tally"] is None and out["holds"] == 0


@pytest.mark.parametrize("support", ["wall", "spotter"])
def test_237_hold_time_is_within_1_s(support: str) -> None:
    holds = [4, 9, 16, 30, 45]
    for seed, fps in ((1, 10), (2, 15), (3, 10)):
        out = node(
            "handstandSession",
            {"holds": holds, "setup": {"support": support}, "seed": seed, "fps": fps},
        )
        assert out["holds"] == len(holds)
        assert abs(out["best"] - max(holds)) <= 1, (seed, out["best"])
        assert abs(out["last"] - holds[-1]) <= 1, (seed, out["last"])
        assert out["drifts"] == 0  # no drift scripted: never a cue
        tally = out["tally"]
        _fits("handstand", tally)
        assert tally["support"] == support and abs(tally["hold_s"] - max(holds)) <= 1
        _plain_view("handstand", out["view"])


def test_237_hips_past_the_limit_cue_come_down_within_a_second_and_count_once() -> None:
    out = node(
        "handstandSession",
        {"holds": [15], "setup": WALL, "drift": {"hold": 0, "at": 4, "amount": 0.25}},
    )
    assert out["drifts"] == 1 and out["tally"]["drifts"] == 1
    assert 0 <= out["overAt"] - out["passAt"] <= 1.0, (out["overAt"], out["passAt"])
    warn = node(
        "handstandSession",
        {"holds": [15], "setup": WALL, "drift": {"hold": 0, "at": 4, "amount": 0.12}, "viewAt": 7},
    )
    assert warn["drifts"] == 0
    assert {"kind": "tip", "text": "Hips drifting. Push tall through your shoulders."} in warn[
        "mid"
    ]


def test_237_the_limit_he_sets_is_the_one_used() -> None:
    small = {"hold": 0, "at": 4, "amount": 0.1}
    loose = node("handstandSession", {"holds": [12], "setup": WALL, "drift": small})
    tight = node(
        "handstandSession",
        {"holds": [12], "setup": {"support": "wall", "limit": 0.12}, "drift": small},
    )
    assert loose["drifts"] == 0 and tight["drifts"] == 1


def test_237_the_spotter_in_view_has_no_hold_and_nothing_kept() -> None:
    out = node(
        "handstandSession", {"holds": [15], "setup": {"support": "spotter"}, "spotter": True}
    )
    assert out["tally"] is None and out["holds"] == 0


def test_237_losing_sight_mid_hold_says_come_down_safely() -> None:
    out = node("handstandSession", {"holds": [20], "setup": WALL, "lostAt": 10})
    assert {"kind": "paused", "why": "I cannot see you. Come down safely."} in out["view"]


# ---- row 239: kettlebell swings ---------------------------------------------------------------
def test_239_swings_are_within_one_per_20_and_a_part_swing_never_counts() -> None:
    for seed, fps, n in ((1, 15, 20), (2, 10, 20), (3, 15, 40)):
        partial = [3, 11] if n == 20 else [5, 17, 29]
        out = node("kettlebellSession", {"fps": fps, "seed": seed, "swings": n, "partial": partial})
        truth = n - len(partial)
        assert abs(out["tally"]["swings"] - truth) <= _per_20(truth), (seed, out["tally"])
        _fits("kettlebell", out["tally"])
        _plain_view("kettlebell", out["view"])


def test_239_hinge_versus_squat_is_right_on_90_percent() -> None:
    right = total = 0
    for seed, fps in ((1, 15), (2, 10), (3, 15), (4, 15)):
        squats = sorted({(seed * 3 + k * 7) % 24 for k in range(8)})
        out = node(
            "kettlebellSession",
            {"fps": fps, "seed": seed, "swings": 24, "squats": squats, "jitter": 8},
        )
        assert len(out["styles"]) == len(out["truth"])
        right += sum(a == b for a, b in zip(out["styles"], out["truth"], strict=True))
        total += len(out["truth"])
        hinges = out["truth"].count("hinge")
        assert abs(out["tally"]["hinge"] - round(100 * hinges / len(out["truth"]))) <= 10
    assert right / total >= 0.9


def test_239_a_squat_swing_gets_the_one_tip_and_a_hinge_the_good_line() -> None:
    squat = node("kettlebellSession", {"swings": 6, "squats": [5]})
    hinge = node("kettlebellSession", {"swings": 6})
    tip = {"kind": "tip", "text": "Push your hips back and keep your shins nearly upright."}
    assert tip in squat["view"] and tip not in hinge["view"]
    assert {"kind": "line", "text": "Good hinge."} in hinge["view"]


def test_239_the_wrist_path_is_drawn_as_the_bells_path() -> None:
    out = node("kettlebellSession", {"swings": 10, "viewAt": 6.2})
    targets = next(w for w in out["mid"] if w["kind"] == "targets")
    ys = [d["y"] for d in targets["dots"]]
    assert 2 <= len(targets["dots"]) <= 8 and max(ys) - min(ys) >= 0.1  # the swing's arc
    assert len(targets["hands"]) == 1  # the bell, where the wrists are now
    assert all(0 <= v <= 1 for d in targets["dots"] for v in (d["x"], d["y"]))


def test_235_rebound_jumps_each_get_their_landing_judged() -> None:
    out = node("reboundJumps", {"jumps": 5})
    assert out["tally"]["jumps"] == 5
    assert out["tally"]["stiff"] == 5  # short, straight-legged contacts: each one judged
