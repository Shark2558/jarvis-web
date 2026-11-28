# tests/test_r81_h_coaches.py -- R8.1 builder H: the partner, walk, sit-to-stand and meal coaches
# (docs/plans/r8-vision.md v8.0.4 section 2.2 rows 240, 263, 269, 247; ROWS.md). Each row's
# acceptance test, on synthetic data only (never a real person's): the console's use cases
# (console-coach-<x>.js) run in Node on the scripted sessions of
# tests/fixtures/r8/tests_sequences.mjs, behind a stand-in for JarvisVision.use that feeds them as
# the engine's driver does (a state per body; a lone body on the phone is "me"; hands reach every
# body's state); row 240's privacy check also runs through the REAL port core (console-vision.js
# in a vm). Every tally must fit its jarvis.coach.usecases model (a tally that doesn't is dropped),
# every view holds only the fixed widget kinds, and no view says anything medical.
from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

import pytest
from r7_fakes_b import use_case_problems
from r8_fakes import FIXTURES, STATIC, run_node

from jarvis.coach.usecases import BY_ID, VIEW_KINDS, parse_tally
from jarvis.coach.words import PRACTICE, STOP, medical_hits

SEQ = FIXTURES / "tests_sequences.mjs"
USE_MODULES = {
    "partner-stretch": "console-coach-partner.js",
    "walk-test": "console-coach-walk.js",
    "sit-to-stand": "console-coach-sitstand.js",
    "meal": "console-coach-meal.js",
}
NOT_CLINICAL = "Practice, not a clinical test."
NOT_YOU = '{"kind":"not-you"}'


def node(call: str, *args: Any) -> Any:
    return run_node(SEQ, f"mod.{call}", *args)


def _texts(view: Iterable[dict[str, Any]]) -> list[str]:
    return [str(v) for w in view for k, v in w.items() if k != "kind" and isinstance(v, str)]


def _fits(use: str, tally: dict[str, Any] | None) -> None:
    assert tally is not None, use
    assert parse_tally(use, tally) is not None, (use, tally)  # never dropped: it fits its model


def _plain_view(use: str, view: list[dict[str, Any]]) -> None:
    assert view and len(view) <= 8, use
    assert {w["kind"] for w in view} <= set(VIEW_KINDS), use
    assert [t for t in _texts(view) if medical_hits(t)] == [], use
    assert STOP in _texts(view), use  # every session says it, before and during


# ---- the guard: each module is a use case, registers once, and asks for its registry tasks ----
@pytest.mark.parametrize("use, name", sorted(USE_MODULES.items()))
def test_each_h_coach_passes_the_use_case_guard_and_registers_once(use: str, name: str) -> None:
    js = (STATIC / name).read_text(encoding="utf-8")
    assert js.isascii() and len(js.splitlines()) <= 400
    assert use_case_problems(js) == [], name
    assert js.count("JarvisVision.use(") == 1
    got = node("registered", name)
    assert got == {"id": use, "tasks": list(BY_ID[use].tasks), "onResult": "function",
                   "summary": "function"}  # fmt: skip
    assert BY_ID[use].module == name


@pytest.mark.parametrize("use, name", sorted(USE_MODULES.items()))
def test_each_h_coach_says_what_to_do_before_a_session(use: str, name: str) -> None:
    out = node("emptySummary", name)
    assert out["tally"] is None
    _plain_view(use, out["view"])


# ---- row 240: assisted stretching with a partner ----------------------------------------------
STRETCHES = [
    {"joint": "hip", "peak": 72, "hold": 15},
    {"joint": "knee", "peak": 118, "hold": 10, "deepen": 6},
    {"joint": "shoulder", "peak": 150, "hold": 20},
    {"joint": "hip", "peak": 45, "hold": 8, "rise": 3},
]


@pytest.mark.parametrize("seed, partner", [(1, "still"), (2, "wild"), (3, "none")])
def test_240_his_ranges_are_within_10_degrees_and_holds_within_a_second(
    seed: int, partner: str
) -> None:
    out = node("partnerSession", {"seed": seed, "partner": partner, "stretches": STRETCHES})
    assert out["kind"] == "you" and out["lost"] is False
    assert len(out["done"]) == len(out["truths"]) == len(STRETCHES)
    for got, want in zip(out["done"], out["truths"], strict=True):
        assert abs(got["range"] - want["range"]) <= 10, (got, want)
        assert abs(got["hold"] - want["hold"]) <= 1, (got, want)
    _fits("partner-stretch", out["tally"])
    assert out["tally"]["stretches"] == len(STRETCHES)
    _plain_view("partner-stretch", out["view"])


def test_240_the_hold_phase_agrees_with_the_script() -> None:
    out = node("partnerSession", {"seed": 4, "partner": "wild", "stretches": STRETCHES})
    h = out["hold"]
    f1 = 2 * h["tp"] / (2 * h["tp"] + h["fp"] + h["fn"])
    assert f1 >= 0.9, h


def test_240_nothing_about_the_partner_is_kept_or_shown() -> None:
    out = node("partnerSession", {"seed": 5, "partner": "wild", "stretches": STRETCHES[:2]})
    assert out["partnerStates"] == [NOT_YOU]  # every state the module returned for the partner
    assert out["partnerHoldsNumbers"] is False  # no point, count, time or angle
    assert out["partnerTally"] is None
    assert out["partnerViewHasNumber"] is False
    _plain_view("partner-stretch", out["partnerView"])


def test_240_his_results_are_the_same_whatever_the_partner_does() -> None:
    runs = [
        node("partnerSession", {"seed": 6, "partner": p, "stretches": STRETCHES})
        for p in ("none", "still", "wild")
    ]
    assert runs[0]["done"] == runs[1]["done"] == runs[2]["done"]
    assert runs[0]["tally"] == runs[1]["tally"] == runs[2]["tally"]


def test_240_no_partner_data_leaves_the_task_through_the_real_driver() -> None:
    out = node("partnerDriver", {"seed": 7, "partner": "wild"})
    assert out["errors"] == []
    assert [t["track"] for t in out["tracks"]] == [0, 1]
    assert out["partnerFrames"] > 100 and out["ownerFrames"] > 100
    assert out["partnerStates"] == [NOT_YOU]
    by_track = {t["track"]: t for t in out["tallies"]}
    assert by_track[1]["tally"] is None
    assert not any(ch.isdigit() for ch in json.dumps(by_track[1]["view"]))
    _fits("partner-stretch", by_track[0]["tally"])
    assert by_track[0]["tally"]["stretches"] == 1
    assert abs(by_track[0]["tally"]["range_deg"] - 65) <= 10
    assert abs(by_track[0]["tally"]["hold_s"] - 8) <= 1


def test_240_it_starts_only_after_the_partner_consent_is_confirmed() -> None:
    out = node("partnerSession", {"seed": 8, "consent": False, "stretches": STRETCHES[:1]})
    assert out["kind"] == "consent" and out["tally"] is None and out.get("done") is None
    assert "Confirm that your partner agrees to be in view." in _texts(out["view"])
    assert out["partnerHoldsNumbers"] is False
    real = node("partnerDriver", {"seed": 8, "consent": False})
    assert real["errors"] == [] and all(t["tally"] is None for t in real["tallies"])


def test_240_a_consent_from_long_ago_starts_nothing() -> None:
    out = node("partnerSession", {"seed": 9, "consentAt": -120, "stretches": STRETCHES[:1]})
    assert out["kind"] == "not-you" and out["tally"] is None


def test_240_two_bodies_from_the_start_are_never_taken_for_him() -> None:
    out = node("partnerSession", {"seed": 10, "partnerAt": 0, "stretches": STRETCHES[:1]})
    assert out["kind"] == "not-you" and out["tally"] is None
    assert "Stand alone in view first: JARVIS keeps only your stretch." in _texts(out["view"])


def test_240_the_partner_alone_later_on_a_new_track_is_never_taken_for_him() -> None:
    plan = [{"joint": "hip", "peak": 60, "hold": 8}, {"joint": "hip", "peak": 60, "hold": 8}]
    out = node("partnerSession", {"seed": 11, "stretches": plan, "partnerAloneAt": 40})
    assert out["aloneTally"] is None and out["partnerHoldsNumbers"] is False
    assert set(out["partnerStates"]) == {NOT_YOU}


def test_240_a_track_swap_ends_his_session_and_keeps_only_his_stretches() -> None:
    plan = [{"joint": "hip", "peak": 60, "hold": 8}, {"joint": "knee", "peak": 110, "hold": 10}]
    clean = node("partnerSession", {"seed": 12, "stretches": plan, "partner": "still"})
    swapped = node(
        "partnerSession", {"seed": 12, "stretches": plan, "partner": "still", "swapAt": 18.5}
    )
    assert swapped["lost"] is True
    assert swapped["done"] == clean["done"][:1]  # the first stretch, his; nothing after the swap
    assert swapped["tally"]["stretches"] == 1
    assert "Lost track of you: start again to go on." in _texts(swapped["view"])


def test_240_a_chosen_stretch_watches_only_that_joint() -> None:
    hip = [{"joint": "hip", "peak": 70, "hold": 10}]
    wrong = node("partnerSession", {"seed": 13, "stretches": hip, "stretch": "knee"})
    right = node("partnerSession", {"seed": 13, "stretches": hip, "stretch": "hip"})
    assert wrong["tally"] is None and right["tally"]["stretches"] == 1


# ---- row 263: the six-minute walk -------------------------------------------------------------
@pytest.mark.parametrize(
    "seed, course, length_s, turn_s",
    [(1, 8, 6, 1.2), (2, 5, 4.5, 0.9), (3, 12, 9, 1.6), (4, 3, 3.2, 0.8)],
)
def test_263_laps_are_exact_and_turns_counted_side_on(
    seed: int, course: float, length_s: float, turn_s: float
) -> None:
    out = node("walkSession", {"seed": seed, "course": course, "lengthS": length_s,
                               "turnS": turn_s, "noise": 0.003})  # fmt: skip
    truth, tally = out["truth"], out["tally"]
    assert truth["margin"] >= 1.0
    _fits("walk-test", tally)
    assert tally["laps"] == truth["laps"] and tally["turns"] == truth["turns"], (tally, truth)
    assert tally["course_m"] == course
    assert tally["metres"] == pytest.approx(truth["laps"] * course)
    _plain_view("walk-test", out["view"])


@pytest.mark.parametrize("seed, course", [(5, 5), (6, 4)])
def test_263_laps_are_exact_and_turns_counted_end_on(seed: int, course: float) -> None:
    out = node("walkSession", {"seed": seed, "view": "end", "course": course, "lengthS": 4.2,
                               "turnS": 1.0, "noise": 0.0015})  # fmt: skip
    tally, truth = out["tally"], out["truth"]
    _fits("walk-test", tally)
    assert tally["laps"] == truth["laps"] and tally["turns"] == truth["turns"], (tally, truth)


def test_263_dropped_frames_and_a_slower_camera_still_count_exactly() -> None:
    out = node("walkSession", {"seed": 7, "fps": 6, "drop": 7, "noise": 0.004})
    assert out["tally"]["laps"] == out["truth"]["laps"]
    assert out["tally"]["turns"] == out["truth"]["turns"]


def test_263_time_up_at_the_end_of_a_length_counts_the_length_but_not_the_turn() -> None:
    out = node("walkSession", {"seed": 8, "ends": "at-end"})
    truth, tally = out["truth"], out["tally"]
    assert truth["atEnd"] is True and truth["laps"] == truth["turns"] + 1
    assert tally["laps"] == truth["laps"] and tally["turns"] == truth["turns"]


@pytest.mark.parametrize("setup", [{}, {"course_m": 0}, {"course_m": 250}, {"course_m": "8"}])
def test_263_it_counts_nothing_until_he_types_the_course_length(setup: dict[str, Any]) -> None:
    out = node("walkSession", {"seed": 9, "setup": setup})
    assert out["tally"] is None
    assert "Type the course length in metres to start." in _texts(out["view"])


def test_263_it_is_labelled_practice_not_a_clinical_test() -> None:
    out = node("walkSession", {"seed": 10})
    assert NOT_CLINICAL in _texts(out["view"])
    assert "Time is up: stop where you are." in _texts(out["view"])
    before = node("emptySummary", "console-coach-walk.js")
    assert NOT_CLINICAL in _texts(before["view"])


# ---- row 269: sit to stand --------------------------------------------------------------------
@pytest.mark.parametrize(
    "seed, fps, rise, sit",
    [(1, 15, 0.9, 1.0), (2, 15, 1.3, 1.2), (3, 15, 0.7, 0.8), (4, 10, 1.0, 1.0), (5, 15, 1.6, 1.4)],
)
def test_269_the_30_second_count_is_exact_and_the_5_times_time_within_0_3_s(
    seed: int, fps: int, rise: float, sit: float
) -> None:
    out = node("sitStandSession", {"seed": seed, "fps": fps, "rise": rise, "sit": sit,
                                   "noise": 0.003})  # fmt: skip
    truth, tally = out["truth"], out["tally"]
    _fits("sit-to-stand", tally)
    assert tally["in_30s"] == truth["in30"], (tally, truth)
    assert abs(tally["five_s"] - truth["five"]) <= 0.3, (tally, truth)
    _plain_view("sit-to-stand", out["view"])


def test_269_a_partial_stand_is_not_counted() -> None:
    out = node("sitStandSession", {"seed": 6, "partial": [2, 4, 5]})
    assert out["truth"]["partial"] == 3
    assert out["tally"]["in_30s"] == out["truth"]["in30"]
    assert abs(out["tally"]["five_s"] - out["truth"]["five"]) <= 0.3


@pytest.mark.parametrize("edge, half", [("above", True), ("below", False)])
def test_269_over_halfway_up_at_30_seconds_counts_a_stand(edge: str, half: bool) -> None:
    out = node("sitStandSession", {"seed": 7, "edge": edge})
    assert out["truth"]["half"] is half
    assert out["tally"]["in_30s"] == out["truth"]["in30"], (out["tally"], out["truth"])


def test_269_fewer_than_five_stands_gives_no_five_times_time() -> None:
    out = node("sitStandSession", {"seed": 8, "count": 4})
    assert out["tally"]["in_30s"] == 4 and out["tally"]["five_s"] == 0


def test_269_rising_before_go_waits_for_a_new_count_in() -> None:
    plain = node("sitStandSession", {"seed": 9})
    early = node("sitStandSession", {"seed": 9, "falseStart": True})
    assert early["go"] > plain["go"] + 1  # the count-in started again once he sat back down
    assert early["tally"]["in_30s"] == early["truth"]["in30"]


def test_269_it_is_labelled_practice_not_a_clinical_test() -> None:
    out = node("sitStandSession", {"seed": 10})
    assert NOT_CLINICAL in _texts(out["view"]) and PRACTICE in _texts(out["view"])


# ---- row 247: eating pace at the table --------------------------------------------------------
@pytest.mark.parametrize("seed, gap, dwell", [(1, 25, 0.5), (2, 15, 0.35), (3, 40, 0.8)])
def test_247_bites_within_10_percent_and_meal_length_within_a_minute(
    seed: int, gap: float, dwell: float
) -> None:
    out = node("mealSession", {"seed": seed, "gapS": gap, "dwell": dwell, "noise": 0.003})
    truth, tally = out["truth"], out["tally"]
    assert truth["other"] > 0  # gestures that are not bites were in the meal
    _fits("meal", tally)
    assert abs(tally["bites"] - truth["bites"]) <= 0.1 * truth["bites"], (tally, truth)
    assert abs(tally["minutes"] - truth["minutes"]) <= 1, (tally, truth)
    assert tally["per_minute"] == pytest.approx(tally["bites"] / tally["minutes"], abs=0.11)
    _plain_view("meal", out["view"])


@pytest.mark.parametrize("target", ["all", "me"])
def test_247_another_person_in_view_pauses_the_count(target: str) -> None:
    others = [[120, 300], [480, 560]]
    out = node("mealSession", {"seed": 4, "others": others, "target": target})
    truth, tally = out["truth"], out["tally"]
    assert truth["bites"] < truth["all"] - 5  # bites he took while someone else was in view
    assert abs(tally["bites"] - truth["bites"]) <= 0.1 * truth["bites"], (tally, truth)
    assert out["pausedViews"]
    for view in out["pausedViews"]:
        assert any(w["kind"] == "paused" for w in view), view
        assert "Someone else is in view: angle the phone at yourself." in _texts(view)


def test_247_the_pose_alone_still_counts_bites() -> None:
    out = node("mealSession", {"seed": 5, "hands": False})
    assert abs(out["tally"]["bites"] - out["truth"]["bites"]) <= 0.1 * out["truth"]["bites"]


def test_247_hands_near_the_chin_or_across_the_table_are_not_bites() -> None:
    out = node("mealSession", {"seed": 6, "minutes": 4, "bites": False})
    assert out["truth"]["bites"] == 0 and out["truth"]["other"] > 8
    assert out["tally"] is None  # a meal with no bite keeps nothing
