# tests/test_r81_f_coaches.py -- R8.1 builder F: the flow and balance coaches
# (docs/plans/r8-vision.md v8.0.4 section 2.2 rows 221, 226, 231, 232, 236;
# docs/plans/r8-integration/ROWS.md). Each row's acceptance test, on synthetic data only (never a
# real person's): the console's use cases (console-coach-<x>.js) run in Node on the scripted
# sessions of tests/fixtures/r8/flow_sequences.mjs, behind a stand-in for JarvisVision.use. The
# workbook's checks are covered too: hold-time error, task-state F1 and repeatability (226),
# sequence recall and hold-time error (231), form-step recognition F1 and sequence completion
# (232), timing error and fairness across styles (236). Every tally must fit its
# jarvis.coach.usecases model (a tally that doesn't is dropped), a recorded routine must fit
# jarvis.coach.store's Routine (angles only), every view holds only the fixed widget kinds, and no
# view says anything medical.
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pytest
from r7_fakes_b import use_case_problems
from r8_fakes import FIXTURES, STATIC, run_node

from jarvis.coach.store import ANGLES_MAX, Routine
from jarvis.coach.usecases import VIEW_KINDS, parse_tally
from jarvis.coach.words import STOP, medical_hits

SEQ = FIXTURES / "flow_sequences.mjs"
USE_MODULES = {
    "yoga": "console-coach-yoga.js",
    "balance": "console-coach-balance.js",
    "pilates": "console-coach-pilates.js",
    "tai-chi": "console-coach-taichi.js",
    "dance": "console-coach-dance.js",
}
YOGA = (
    *("mountain", "tree", "warrior_i", "warrior_ii", "triangle", "chair", "cobra", "child"),
    *("downward_dog", "bridge", "cat_cow", "seated_forward_bend"),
)
PILATES = (
    *("hundred", "roll_up", "leg_circle", "single_leg_stretch", "spine_stretch", "teaser"),
    *("swan", "shoulder_bridge"),
)
STYLES = ("lyrical", "pop", "bhangra", "classical")


def node(call: str, *args: Any) -> Any:
    return run_node(SEQ, f"mod.{call}", *args)


def _texts(view: Iterable[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for w in view:
        out += [str(v) for k, v in w.items() if k != "kind" and isinstance(v, str)]
        out += [str(i.get("text")) for i in w.get("items") or [] if isinstance(i, dict)]
    return out


def _fits(use: str, tally: dict[str, Any] | None) -> None:
    assert tally is not None, use
    assert parse_tally(use, tally) is not None, (use, tally)  # never dropped: it fits its model


def _plain_view(use: str, view: list[dict[str, Any]]) -> None:
    assert view and len(view) <= 8, use
    assert {w["kind"] for w in view} <= set(VIEW_KINDS), use
    assert [t for t in _texts(view) if medical_hits(t)] == [], use
    assert STOP in _texts(view), use


def _no_points(value: Any) -> None:
    """Nothing kept is a point: no x/y pair anywhere."""
    if isinstance(value, dict):
        assert not ({"x", "y"} <= set(value)), value
        for v in value.values():
            _no_points(v)
    elif isinstance(value, list):
        for v in value:
            _no_points(v)


# ---- the guard: each module is a use case, registers once, and keeps nothing -------------------
@pytest.mark.parametrize("use, name", sorted(USE_MODULES.items()))
def test_each_flow_coach_passes_the_use_case_guard_and_registers_once(use: str, name: str) -> None:
    js = (STATIC / name).read_text(encoding="utf-8")
    assert js.isascii() and len(js.splitlines()) <= 400
    assert use_case_problems(js) == [], name
    assert js.count("JarvisVision.use(") == 1 and f"id: '{use}'" in js


# ---- row 221: yoga -------------------------------------------------------------------------------
def _yoga_runs() -> list[dict[str, Any]]:
    runs = []
    for seed in range(1, 9):
        out = node(
            "yogaSession",
            {
                "poses": list(YOGA),
                "hold": 6 + seed % 4,
                "seed": seed,
                "tilt": (-4, 0, 3, 4)[seed % 4],
                "scale": (0.72, 0.8, 0.86)[seed % 3],
                "flip": seed % 2 == 0,
            },  # fmt: skip
        )
        runs.append(out)
    return runs


@pytest.fixture(scope="module")
def yoga_runs() -> list[dict[str, Any]]:
    return _yoga_runs()


@pytest.mark.parametrize("pose", YOGA)
def test_221_each_pose_is_recognised_on_90_percent_of_holds(
    pose: str, yoga_runs: list[dict[str, Any]]
) -> None:
    holds = [m for run in yoga_runs for m in run["matched"] if m["pose"] == pose]
    right = [m for m in holds if m["got"] == pose]
    assert len(holds) == 8 and len(right) / len(holds) >= 0.9, (pose, holds)


def test_221_every_recognised_hold_is_timed_within_a_second(
    yoga_runs: list[dict[str, Any]],
) -> None:
    for run in yoga_runs:
        for m in run["matched"]:
            if m["got"] == m["pose"]:
                assert abs(m["got_s"] - m["truth_s"]) <= 1.0, m
        assert run["holds"] == len(YOGA)  # one hold a pose: passing through a shape never counts
        _fits("yoga", run["tally"])
        _plain_view("yoga", run["view"])


def test_221_the_tally_keeps_the_longest_hold_and_the_number_of_holds() -> None:
    out = node(
        "yogaSession", {"poses": ["tree", "warrior_ii", "child"], "hold": [8, 14, 6], "seed": 3}
    )
    assert out["tally"]["pose"] == "warrior_ii" and out["tally"]["holds"] == 3
    assert abs(out["tally"]["hold_s"] - 14) <= 1.0
    _fits("yoga", out["tally"])


def test_221_standing_at_rest_is_no_pose_and_keeps_nothing() -> None:
    out = node("yogaSession", {"poses": [], "rest": 30, "seed": 2})
    assert out["holds"] == 0 and out["tally"] is None
    assert any(w["kind"] == "line" for w in out["view"])


def test_221_a_short_hold_is_not_counted() -> None:
    out = node("yogaSession", {"poses": ["triangle"], "hold": 1, "seed": 4})
    assert out["holds"] == 0 and out["tally"] is None


# ---- row 226: single-leg balance -----------------------------------------------------------------
@pytest.mark.parametrize(
    "stand, front, seed",
    [("left", False, 1), ("right", False, 2), ("left", True, 3), ("right", True, 4)],
)
def test_226_hold_time_is_within_a_second_and_the_state_f1_is_high(
    stand: str, front: bool, seed: int
) -> None:
    holds = [[2.0, 14.5], [18.0, 31.0]]
    out = node("balanceSession", {"stand": stand, "front": front, "seed": seed, "holds": holds,
                                  "seconds": 34, "sway": 1.5})  # fmt: skip
    assert len(out["log"]) == 2, out["log"]
    for got, truth in zip(out["log"], out["truth"], strict=True):
        assert abs(got["s"] - truth) <= 1.0, (got, truth)
        assert got["side"] == stand
    assert out["f1"] >= 0.95, out
    assert out["tally"]["side"] == stand and abs(out["tally"]["hold_s"] - 13.0) <= 1.0
    _fits("balance", out["tally"])
    _plain_view("balance", out["view"])


def test_226_the_sway_score_rises_with_every_step_of_injected_sway() -> None:
    for seed, front in ((5, False), (6, True)):
        scores = [
            node("balanceSession", {"sway": s, "seed": seed, "front": front})["tally"]["sway"]
            for s in (0, 0.5, 1, 2, 3, 4, 6)
        ]
        assert all(b > a for a, b in zip(scores, scores[1:], strict=False)), (front, scores)


def test_226_the_same_stand_gives_the_same_result_and_other_noise_nearly_the_same() -> None:
    first = node("balanceSession", {"sway": 2, "seed": 7})
    again = node("balanceSession", {"sway": 2, "seed": 7})
    assert first["tally"] == again["tally"]
    others = [node("balanceSession", {"sway": 2, "seed": s})["tally"] for s in (8, 9, 10)]
    for t in others:
        assert abs(t["hold_s"] - first["tally"]["hold_s"]) <= 1.0
        assert abs(t["sway"] - first["tally"]["sway"]) <= 10, (t, first["tally"])


def test_226_both_feet_down_is_no_hold() -> None:
    out = node("balanceSession", {"holds": [], "seconds": 15})
    assert out["log"] == [] and out["tally"] is None and out["tp"] == 0 and out["fp"] == 0


# ---- row 231: Pilates ----------------------------------------------------------------------------
def test_231_steps_are_recognised_on_90_percent_and_held_within_a_second() -> None:
    found = total = 0
    for seed in (1, 2, 3, 4):
        out = node("pilatesSession", {"seed": seed, "hold": 4 + seed})
        steps = [g["step"] for g in out["log"]]
        total += len(out["truth"])
        found += len([s for s in steps if s in PILATES])
        for got, truth in zip(out["log"], out["truth"], strict=False):
            if got["step"] == truth["step"]:
                assert abs(got["s"] - truth["s"]) <= 1.0, (got, truth)
        assert out["tally"]["out_of_order"] == 0 and out["wrong"] == []
        _fits("pilates", out["tally"])
        _plain_view("pilates", out["view"])
    assert found / total >= 0.9, (found, total)


@pytest.mark.parametrize(
    "order",
    [
        ["hundred", "roll_up", "single_leg_stretch", "leg_circle", "spine_stretch", "teaser"],
        ["roll_up", "hundred", "leg_circle", "teaser", "spine_stretch", "swan", "shoulder_bridge"],
        ["hundred", "swan", "roll_up", "leg_circle", "shoulder_bridge", "teaser"],
    ],
)
def test_231_every_out_of_order_step_is_reported(order: list[str]) -> None:
    out = node("pilatesSession", {"steps": order, "seed": 5})
    assert [g["step"] for g in out["log"]] == order
    assert out["tally"]["out_of_order"] == len(out["wrong"]) > 0
    for step in out["wrong"]:  # each one said, by name, when it happened
        assert any(step.replace("_", " ").split()[0] in tip.lower() for tip in out["tips"]), (
            step,
            out["tips"],
        )
    marks = next(w for w in out["view"] if w["kind"] == "checklist")["items"]
    assert sum(1 for i in marks if i["ok"] is False) == len(out["wrong"])
    _fits("pilates", out["tally"])


def test_231_a_skipped_step_is_never_counted_as_done() -> None:
    order = [s for s in PILATES if s != "teaser"]
    out = node("pilatesSession", {"steps": order, "seed": 6})
    assert "teaser" not in [g["step"] for g in out["log"]]
    assert out["tally"]["done"] == len(order) and out["tally"]["out_of_order"] == 0


# ---- row 232: tai-chi ----------------------------------------------------------------------------
@pytest.fixture(scope="module")
def taichi_reference() -> list[list[float]]:
    rec = node("taichiSession", {"mode": "record", "seed": 11})
    rows: list[list[float]] = run_node(SEQ, "mod.rowsOf", rec)
    assert (
        rec["tally"]["record"]["rid"] == "tai-chi-1" and rec["tally"]["record"]["kind"] == "tai-chi"
    )
    return rows


def test_232_the_recording_is_angles_only_and_fits_the_routine_store(
    taichi_reference: list[list[float]],
) -> None:
    routine = Routine.model_validate({"kind": "tai-chi", "angles": taichi_reference})
    assert 200 <= len(routine.angles) <= ANGLES_MAX and {len(r) for r in routine.angles} == {9}
    _no_points(taichi_reference)


@pytest.mark.parametrize("tempo, seed", [(1.0, 1), (0.8, 2), (1.25, 3), (1.1, 4)])
def test_232_steps_are_recognised_against_his_reference_with_f1_over_90_percent(
    tempo: float, seed: int, taichi_reference: list[list[float]]
) -> None:
    out = node("taichiSession", {"reference": taichi_reference, "tempo": tempo, "seed": seed})
    assert out["steps"] == 8
    done = [m["step"] for m in out["marks"] if m["done"]]
    tp = len([s for s in done if s in out["performed"]])
    fp, fn = len(done) - tp, len(out["performed"]) - tp
    assert tp / len(out["performed"]) >= 0.9 and 2 * tp / (2 * tp + fp + fn) >= 0.9, out["marks"]
    assert out["tally"]["done"] == len(done)
    _fits("tai-chi", out["tally"])
    _plain_view("tai-chi", out["view"])


def test_232_a_skipped_step_is_not_claimed(taichi_reference: list[list[float]]) -> None:
    out = node("taichiSession", {"reference": taichi_reference, "skip": [4], "seed": 5})
    done = [m["step"] for m in out["marks"] if m["done"]]
    assert 4 not in done and len([s for s in done if s in out["performed"]]) >= 7


def test_232_the_smoothness_score_is_lower_for_every_sequence_with_injected_jerks(
    taichi_reference: list[list[float]],
) -> None:
    for seed in (6, 7):
        clean = node("taichiSession", {"reference": taichi_reference, "seed": seed})
        last = clean["tally"]["smooth"]
        for jerks in ([9.0], [9.0, 21.0], [5.0, 11.0, 17.0, 23.0]):
            jerky = node(
                "taichiSession", {"reference": taichi_reference, "seed": seed, "jerks": jerks}
            )
            assert jerky["tally"]["smooth"] < last, (seed, jerks, jerky["tally"], last)
            last = jerky["tally"]["smooth"]


# ---- row 236: dance ------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def dance_runs() -> dict[str, dict[str, Any]]:
    runs: dict[str, dict[str, Any]] = {}
    for style in STYLES:
        rec = node("danceSession", {"mode": "record", "style": style, "seed": 21, "routine": 3})
        rows = run_node(SEQ, "mod.rowsOf", rec)
        play = {"style": style, "reference": rows, "routine": 3}
        runs[style] = {
            "record": rec,
            "rows": rows,
            "sync": node("danceSession", {**play, "seed": 22}),
            "late": node("danceSession", {**play, "seed": 23, "offset": 0.5}),
            "early": node("danceSession", {**play, "seed": 24, "offset": -0.5}),
        }
    return runs


@pytest.mark.parametrize("style", STYLES)
def test_236_the_sync_score_drops_by_20_points_for_a_half_second_offset(
    style: str, dance_runs: dict[str, dict[str, Any]]
) -> None:
    run = dance_runs[style]
    sync = run["sync"]["tally"]["sync"]
    assert sync >= 80, (style, run["sync"]["tally"])
    for off in ("late", "early"):
        assert sync - run[off]["tally"]["sync"] >= 20, (style, off, run[off]["tally"], sync)
        _fits("dance", run[off]["tally"])
    assert run["late"]["lag"] < -0.3 < 0.3 < run["early"]["lag"]  # timing error: behind, ahead
    assert abs(run["sync"]["lag"]) <= 0.15
    _fits("dance", run["sync"]["tally"])
    _plain_view("dance", run["sync"]["view"])


def test_236_in_time_scores_are_fair_across_styles(dance_runs: dict[str, dict[str, Any]]) -> None:
    scores = [run["sync"]["tally"]["sync"] for run in dance_runs.values()]
    drops = [r["sync"]["tally"]["sync"] - r["late"]["tally"]["sync"] for r in dance_runs.values()]
    assert max(scores) - min(scores) <= 10, scores
    assert max(drops) - min(drops) <= 15, drops


def test_236_his_reference_routine_is_kept_as_joint_angles_only(
    dance_runs: dict[str, dict[str, Any]],
) -> None:
    for run in dance_runs.values():
        rec = run["record"]["tally"]["record"]
        assert rec["rid"] == "dance-3" and rec["kind"] == "dance"
        routine = Routine.model_validate({"kind": "dance", "angles": run["rows"]})
        assert {len(r) for r in routine.angles} == {9} and len(routine.angles) >= 380
        _no_points(run["record"]["tally"])
        assert parse_tally("dance", run["record"]["tally"]) is None  # a recording is not a result


def test_236_without_a_reference_the_session_records_one() -> None:
    out = node("danceSession", {"seconds": 6})
    assert (
        out["tally"]["record"]["rid"] == "dance-1" and len(run_node(SEQ, "mod.rowsOf", out)) >= 55
    )
    _plain_view("dance", out["view"])
