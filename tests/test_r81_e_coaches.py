# tests/test_r81_e_coaches.py -- R8.1 builder E (docs/plans/r8-vision.md v8.0.4 section 2.2;
# ROWS.md): the strength and form coaches' acceptance tests, each run in Node on synthetic bodies
# (tests/fixtures/r8/strength_sequences.mjs) through the REAL use-case modules, and their tallies
# held to jarvis.coach.usecases' models.
#   132 reps         reps within +-1 per set of 10 for six exercises; tempo within +-0.3 s
#   218 warm-up      >= 95 % of the warm-up moves ticked; a wrong move never ticks an item
#   219 band         reps +-1 per 10; a prompt within 1 s when the holding hand leaves
#   220 form         each rule on >= 90 % of faulty reps, <= 5 % of clean ones; one tip a rep
#   222 plank        hold time +-1 s; sag and pike flagged on >= 90 % of spans, <= 5 % false
#   223 space-check  "clear" / "not clear, move the <thing>" right on every fixture; keeps nothing
# Cross-cutting: every view uses the fixed widgets and says nothing medical; every tally fits its
# model; the modules pass the use-case guard. Nothing here is a real person's data.
from __future__ import annotations

from functools import cache
from typing import Any

import pytest
from r7_fakes_b import use_case_problems
from r8_fakes import FIXTURES, STATIC, run_node

from jarvis.coach.usecases import BY_ID, VIEW_KINDS, parse_tally
from jarvis.coach.words import medical_hits

pytestmark = pytest.mark.skipif(
    __import__("shutil").which("node") is None, reason="node is not installed"
)
SEQ = FIXTURES / "strength_sequences.mjs"
MODULES = {
    "reps": "console-coach-reps.js",
    "warm-up": "console-coach-warmup.js",
    "band": "console-coach-band.js",
    "form": "console-coach-form.js",
    "plank": "console-coach-plank.js",
    "space-check": "console-coach-space.js",
}
EXERCISES = ("squat", "lunge", "push_up", "curl", "shoulder_press", "jumping_jack")
TEMPOS = ((1.0, 1.0), (1.5, 1.0), (2.0, 1.0), (3.0, 1.5))
FAULTS = (
    ("squat", False, "depth"),
    ("squat", False, "back"),
    ("squat", True, "knees_in"),
    ("push_up", False, "depth"),
    ("push_up", False, "hips"),
    ("push_up", True, "elbows"),
)
CLEAN = (("squat", False), ("squat", True), ("push_up", False), ("push_up", True))
WARM_UP = (("reach", 5), ("knees", 10), ("squat", 5), ("bend", 6), ("hinge", 5), ("jack", 10))
WRONG = ("calf", "wave", "curl", "halfsquat")


def _many(calls: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    out = run_node(SEQ, "mod.many", [[n, o] for n, o in calls])
    assert isinstance(out, list) and len(out) == len(calls)
    return out


def _checked(use: str, out: dict[str, Any]) -> dict[str, Any]:
    """Every view: fixed widgets only, nothing medical; the tally fits the use case's model."""
    for w in out["view"]:
        assert w["kind"] in VIEW_KINDS, w
        for v in w.values():
            if isinstance(v, str):
                assert medical_hits(v) == [], v
    if out["tally"] is not None:
        assert parse_tally(use, out["tally"]) is not None, out["tally"]
    return out


# ---- row 132: reps and tempo ---------------------------------------------------------------------
@cache
def _reps_runs() -> tuple[tuple[str, float, float, dict[str, Any]], ...]:
    runs = [(e, d, u) for e in EXERCISES for d, u in TEMPOS]
    calls: list[tuple[str, dict[str, Any]]] = [
        (
            "repsSession",
            {"exercise": e, "reps": 10, "down": d, "up": u, "noise": 0.004, "seed": i + 1},
        )
        for i, (e, d, u) in enumerate(runs)
    ]
    outs = _many(calls)
    return tuple((e, d, u, o) for (e, d, u), o in zip(runs, outs, strict=True))


@pytest.mark.parametrize("exercise", EXERCISES)
def test_reps_are_within_one_per_set_of_ten_and_named(exercise: str) -> None:
    for ex, _d, _u, out in _reps_runs():
        if ex != exercise:
            continue
        tally = _checked("reps", out)["tally"]
        assert tally["exercise"] == exercise
        assert abs(tally["reps"] - 10) <= 1 and tally["sets"] == 1


@pytest.mark.parametrize("exercise", EXERCISES)
def test_tempo_down_and_up_are_within_a_third_of_a_second(exercise: str) -> None:
    for ex, down, up, out in _reps_runs():
        if ex != exercise:
            continue
        tally = out["tally"]
        assert abs(tally["down_s"] - down) <= 0.3, (down, tally)
        assert abs(tally["up_s"] - up) <= 0.3, (up, tally)


def test_half_reps_never_count_and_lost_frames_cost_nothing() -> None:
    half, part, dropped, slow = _many(
        [
            ("repsSession", {"exercise": "squat", "reps": 10, "halfEvery": 2}),
            ("repsSession", {"exercise": "push_up", "reps": 10, "deep": 0.45}),
            ("repsSession", {"exercise": "curl", "reps": 10, "drop": 4, "noise": 0.004}),
            ("repsSession", {"exercise": "squat", "reps": 10, "fps": 10, "noise": 0.004}),
        ]
    )
    assert half["tally"]["reps"] == half["truth"]["reps"] == 5  # every 2nd rep half way
    assert part["tally"] is None  # nothing but part reps: nothing to keep
    assert abs(dropped["tally"]["reps"] - 10) <= 1  # every fourth frame lost
    assert abs(slow["tally"]["reps"] - 10) <= 1  # a slower phone (10 a second)


def test_a_rest_starts_a_new_set_and_the_view_shows_this_sets_reps() -> None:
    (out,) = _many([("repsSession", {"exercise": "squat", "reps": 10, "gapAfter": 5, "gap": 25})])
    tally, view = _checked("reps", out)["tally"], out["view"]
    assert tally["sets"] == 2 and tally["reps"] == 10
    big = next(w for w in view if w["kind"] == "big")
    assert big["n"] == 5 and big["word"] == "reps"
    texts = [w.get("text", "") for w in view]
    assert "Set 2" in texts and "Squats" in texts and "Stop if anything hurts." in texts


# ---- row 220: form rules -------------------------------------------------------------------------
@cache
def _form_runs() -> tuple[dict[str, Any], ...]:
    calls = [
        (
            "formSession",
            {"exercise": e, "front": f, "faults": [fault] * 10, "seed": s, "noise": 0.004},
        )
        for e, f, fault in FAULTS
        for s in (1, 2)
    ]
    calls += [
        ("formSession", {"exercise": e, "front": f, "faults": [""] * 10, "seed": s, "noise": 0.004})
        for e, f in CLEAN
        for s in (1, 2)
    ]
    return tuple(_many(calls))


@pytest.mark.parametrize("case", range(len(FAULTS)), ids=[f"{e}-{f}" for e, _v, f in FAULTS])
def test_each_form_rule_fires_on_nine_in_ten_faulty_reps(case: int) -> None:
    runs = _form_runs()[2 * case : 2 * case + 2]
    fault = FAULTS[case][2]
    log = [x for r in runs for x in r["log"]]
    assert len(log) == 20  # every rep counted, shallow ones too
    assert sum(1 for x in log if x == fault) >= 18, log
    tips = [w for r in runs for w in r["view"] if w["kind"] == "tip"]
    assert tips and all(medical_hits(w["text"]) == [] for w in tips)


def test_clean_reps_get_a_tip_at_most_one_in_twenty() -> None:
    clean = _form_runs()[2 * len(FAULTS) :]
    log = [x for r in clean for x in r["log"]]
    assert len(log) == 80
    assert sum(1 for x in log if x) <= 4, log  # <= 5 % false
    for r in clean:
        t = _checked("form", r)["tally"]
        assert t["reps"] == 10 and t["clean"] + t["tips"] == t["reps"]


def test_one_tip_a_rep_at_most() -> None:
    (out,) = _many(
        [("formSession", {"exercise": "squat", "faults": ["back", "depth", "", "back"], "seed": 4})]
    )
    assert out["log"] == ["back", "depth", "", "back"]  # one entry, one rule, per rep
    assert sum(1 for w in out["view"] if w["kind"] == "tip") <= 1
    assert _checked("form", out)["tally"]["tips"] == 3


# ---- row 218: the warm-up checklist --------------------------------------------------------------
def test_the_warm_up_ticks_every_move_done_and_no_wrong_one() -> None:
    calls: list[tuple[str, dict[str, Any]]] = [
        ("warmupSession", {"moves": list(WARM_UP), "seed": s, "noise": 0.004}) for s in (1, 2, 3)
    ]
    calls += [("warmupSession", {"moves": [m], "seed": 5}) for m in WARM_UP]
    calls += [("warmupSession", {"moves": [[w, 12]], "seed": 6}) for w in WRONG]
    outs = _many(calls)
    full, single, wrong = outs[:3], outs[3:9], outs[9:]
    ticked = sum(_checked("warm-up", o)["tally"]["done"] for o in full)
    assert ticked >= 0.95 * 3 * len(WARM_UP)
    for (move, times), o in zip(WARM_UP, single, strict=True):
        assert o["done"][move] == times and sum(o["done"].values()) == times, (move, o["done"])
    for w, o in zip(WRONG, wrong, strict=True):
        assert sum(o["done"].values()) == 0 and o["tally"] is None, (w, o["done"])
    items = next(w for w in full[0]["view"] if w["kind"] == "checklist")["items"]
    assert len(items) == 6 and all(i["ok"] is True for i in items)


# ---- row 219: the band ---------------------------------------------------------------------------
def test_band_reps_and_the_holding_hand_prompt() -> None:
    plain, out, blink, part = _many(
        [
            ("bandSession", {"reps": 10, "noise": 0.004}),
            ("bandSession", {"reps": 10, "outAt": [8, 16], "outFor": 2}),
            ("bandSession", {"reps": 10, "blink": 7}),
            ("bandSession", {"reps": 10, "partial": 3}),
        ]
    )
    assert abs(_checked("band", plain)["tally"]["reps"] - 10) <= 1 and plain["prompts"] == []
    assert [round(p - a, 3) for p, a in zip(out["prompts"], (8, 16), strict=True)] == [
        pytest.approx(d, abs=0.05) for d in (0.333, 0.333)
    ]
    assert all(p - a < 1.0 for p, a in zip(out["prompts"], (8, 16), strict=True))
    assert _checked("band", out)["tally"]["prompts"] == 2
    assert blink["prompts"] == [] and abs(blink["tally"]["reps"] - 10) <= 1
    assert part["tally"]["reps"] == part["truth"]["reps"]  # a part pull never counts


# ---- row 222: the plank --------------------------------------------------------------------------
def test_plank_hold_time_and_alignment_spans() -> None:
    spans = [[4, 8, "sag"], [12, 15, "pike"], [20, 24, "sag"], [28, 31, "pike"], [35, 39, "sag"]]
    calls: list[tuple[str, dict[str, Any]]] = [
        ("plankSession", {"hold": h, "seed": s}) for h, s in ((20, 1), (45, 2), (60, 3))
    ]
    calls += [
        ("plankSession", {"hold": 45, "faults": spans, "wobble": 3, "seed": s}) for s in (4, 5)
    ]
    calls += [("plankSession", {"hold": 60, "wobble": 3, "seed": s}) for s in (6, 7, 8)]
    outs = _many(calls)
    for o, h in zip(outs[:3], (20, 45, 60), strict=True):
        assert abs(_checked("plank", o)["tally"]["hold_s"] - h) <= 1
    flagged = sum(o["tally"]["sags"] + o["tally"]["pikes"] for o in outs[3:5])
    assert flagged >= 0.9 * 2 * len(spans)
    assert all(o["tally"]["sags"] == 3 and o["tally"]["pikes"] == 2 for o in outs[3:5])
    false = sum(o["tally"]["sags"] + o["tally"]["pikes"] for o in outs[5:])
    assert false == 0 and all(abs(o["tally"]["hold_s"] - 60) <= 1 for o in outs[5:])


# ---- row 223: the space check --------------------------------------------------------------------
def _thing(
    label: str, x: float, y: float, w: float, h: float, score: float = 0.8
) -> dict[str, Any]:
    return {"label": label, "score": score, "box": {"x": x, "y": y, "w": w, "h": h}}


SPACE: tuple[tuple[str, list[dict[str, Any]], str], ...] = (
    ("nothing", [], ""),
    ("a chair beside him", [_thing("chair", 0.7, 0.5, 0.15, 0.35)], "chair"),
    ("a television on the wall", [_thing("tv", 0.1, 0.1, 0.3, 0.2)], ""),
    ("a chair across the room", [_thing("chair", 0.95, 0.5, 0.05, 0.35)], ""),
    ("a bottle on a shelf", [_thing("bottle", 0.3, 0.1, 0.05, 0.1)], ""),
    (
        "a ball at his feet, a chair further",
        [_thing("chair", 0.75, 0.5, 0.1, 0.35), _thing("sports_ball", 0.55, 0.8, 0.06, 0.06)],
        "ball",
    ),
    ("a faint chair", [_thing("chair", 0.6, 0.5, 0.2, 0.35, 0.2)], ""),
    ("a table", [_thing("dining_table", 0.2, 0.55, 0.25, 0.3)], "table"),
    ("the dog", [_thing("dog", 0.35, 0.7, 0.15, 0.15)], "dog"),
    ("a person behind him", [_thing("person", 0.6, 0.2, 0.2, 0.7)], ""),
)


def test_the_space_check_is_right_on_every_fixture_and_keeps_nothing() -> None:
    outs = _many([("spaceCheck", {"things": things}) for _n, things, _w in SPACE])
    for (name, _t, want), out in zip(SPACE, outs, strict=True):
        assert out["tally"] is None, name
        texts = [w["text"] for w in _checked("space-check", out)["view"] if "text" in w]
        if want:
            assert f"Not clear: move the {want}." in texts, (name, texts)
        else:
            assert "Clear: nothing in your space to trip on or hit." in texts, (name, texts)
    assert BY_ID["space-check"].keeps is False


def test_the_space_check_waits_for_three_looks() -> None:
    (out,) = _many([("spaceCheck", {"things": [], "looks": 2})])
    assert [w["text"] for w in out["view"]][0] == "Looking around you…"


# ---- the guard -----------------------------------------------------------------------------------
@pytest.mark.parametrize("use", sorted(MODULES))
def test_each_module_is_a_use_case_the_guard_passes(use: str) -> None:
    src = (STATIC / MODULES[use]).read_text(encoding="utf-8")
    assert use_case_problems(src) == []
    assert f"JarvisVision.use({{ id: '{use}'" in src and src.isascii()
    assert BY_ID[use].module == MODULES[use] and BY_ID[use].release == "R8.1"
