# evals/r8_1/strength.py
"""R8.1 eval, builder E (`strength`): the strength and form coaches' pass bars (docs/plans/
r8-vision.md v8.0.4 sections 2.2 and 8), on synthetic data only -- tests/fixtures/r8/
strength_sequences.mjs (Node: the console's real use-case modules). No public dataset is used, so
none needs a licence here.

    python evals/r8_1/strength.py         runs the cases and the controls; exit 1 on a failure

Cases (each {"id": "strength:<case>", "passed", "failures"}):
  reps          row 132: reps within 1 per set of 10 for six exercises; tempo within 0.3 s
  half_reps     row 132: a rep only half way down never counts
  form          row 220: each rule on >= 90 % of faulty reps and <= 5 % of clean ones
  warm_up       row 218: >= 95 % of the moves ticked; a wrong move never ticks an item
  band          row 219: reps within 1 per 10; a prompt within 1 s each time the hand leaves
  plank         row 222: hold time within 1 s; >= 90 % of sag and pike spans flagged, none false
  space         row 223: "clear" / "not clear, move the <thing>" right on every fixture list
  tallies       every tally the sessions made fits its model, and none holds a point
  not_medical   no view any session made says anything medical (jarvis.coach.words)

Negative controls (each must make its case fail, or the suite proves nothing):
  half_counts      the squat counter takes a dip to 140 degrees (a coach that counts half reps)
  point_in_tally   a tally carries a body point
  medical_view     a view says "Your blood pressure is in the normal range."
  faint_things     the space check names things seen with any certainty
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / "src", ROOT / "tests"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from r8_fakes import FIXTURES, STATIC, run_node  # noqa: E402

from jarvis.coach.usecases import parse_tally  # noqa: E402
from jarvis.coach.words import medical_hits  # noqa: E402

Case = dict[str, Any]
SEQ = FIXTURES / "strength_sequences.mjs"
STATE: dict[str, Any] = {"base": None, "kept": [], "plant": None}
EXERCISES = ("squat", "lunge", "push_up", "curl", "shoulder_press", "jumping_jack")
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


def _thing(
    label: str, x: float, y: float, w: float, h: float, score: float = 0.8
) -> dict[str, Any]:
    return {"label": label, "score": score, "box": {"x": x, "y": y, "w": w, "h": h}}


SPACE: tuple[tuple[list[dict[str, Any]], str], ...] = (
    ([], ""),
    ([_thing("chair", 0.7, 0.5, 0.15, 0.35)], "chair"),
    ([_thing("tv", 0.1, 0.1, 0.3, 0.2)], ""),
    ([_thing("chair", 0.95, 0.5, 0.05, 0.35)], ""),
    ([_thing("bottle", 0.3, 0.1, 0.05, 0.1)], ""),
    ([_thing("chair", 0.75, 0.5, 0.1, 0.35), _thing("sports_ball", 0.55, 0.8, 0.06, 0.06)], "ball"),
    ([_thing("chair", 0.6, 0.5, 0.2, 0.35, 0.2)], ""),
    ([_thing("dining_table", 0.2, 0.55, 0.25, 0.3)], "table"),
)


USE_OF = {
    "repsSession": "reps",
    "formSession": "form",
    "warmupSession": "warm-up",
    "bandSession": "band",
    "plankSession": "plank",
    "spaceCheck": "space-check",
}


def _many(calls: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    base = STATE["base"]
    batch = [[n, dict(o, base=base) if base else o] for n, o in calls]
    out: list[dict[str, Any]] = run_node(SEQ, "mod.many", batch)
    for (name, _o), r in zip(calls, out, strict=True):
        use = USE_OF[name]
        if STATE["plant"]:
            r = STATE["plant"](r)
        STATE["kept"].append((use, r))
    return [r for _u, r in STATE["kept"][-len(calls) :]]


def _case(name: str, failures: list[str]) -> Case:
    return {"id": f"strength:{name}", "passed": not failures, "failures": failures[:10]}


def reps() -> Case:
    runs = [(e, d, u) for e in EXERCISES for d, u in ((1.5, 1.0), (3.0, 1.5))]
    calls = [
        ("repsSession", {"exercise": e, "down": d, "up": u, "noise": 0.004, "seed": i + 1})
        for i, (e, d, u) in enumerate(runs)
    ]
    bad = []
    for (_n, o), r in zip(calls, _many(calls), strict=True):
        t = r["tally"] or {}
        if (
            abs(t.get("reps", -9) - 10) > 1
            or abs(t.get("down_s", -9) - o["down"]) > 0.3
            or abs(t.get("up_s", -9) - o["up"]) > 0.3
        ):
            bad.append(f"{o['exercise']} {o['down']}/{o['up']}: {t}")  # fmt: skip
    return _case("reps", bad)


def half_reps() -> Case:
    (r,) = _many([("repsSession", {"exercise": "squat", "halfEvery": 2})])
    got = (r["tally"] or {}).get("reps")
    return _case("half_reps", [] if got == 5 else [f"counted {got} of 5 full reps"])


def form() -> Case:
    bad = []
    calls = [
        ("formSession", {"exercise": e, "front": f, "faults": [x] * 10, "seed": 2})
        for e, f, x in FAULTS
    ]
    calls += [
        ("formSession", {"exercise": e, "front": f, "faults": [""] * 10, "seed": 3})
        for e, f in CLEAN
    ]
    out = _many(calls)
    for (e, f, x), r in zip(FAULTS, out[: len(FAULTS)], strict=True):
        if sum(1 for y in r["log"] if y == x) < 9:
            bad.append(f"{e} front={f} {x}: {r['log']}")
    false = sum(1 for r in out[len(FAULTS) :] for y in r["log"] if y)
    if false > 2:  # <= 5 % of 40 clean reps
        bad.append(f"{false} tips on 40 clean reps")
    return _case("form", bad)


def warm_up() -> Case:
    out = _many([("warmupSession", {"moves": list(WARM_UP), "noise": 0.004, "seed": 7})]
                + [("warmupSession", {"moves": [[w, 12]], "seed": 8}) for w in WRONG])  # fmt: skip
    bad = [] if (out[0]["tally"] or {}).get("done", 0) >= 6 else [f"ticked {out[0]['done']}"]
    bad += [
        f"{w} ticked {r['done']}"
        for w, r in zip(WRONG, out[1:], strict=True)
        if sum(r["done"].values())
    ]
    return _case("warm_up", bad)


def band() -> Case:
    plain, out = _many([("bandSession", {"noise": 0.004}), ("bandSession", {"outAt": [8, 16]})])
    bad = (
        [] if abs((plain["tally"] or {}).get("reps", -9) - 10) <= 1 else [f"reps {plain['tally']}"]
    )
    late = [p - a for p, a in zip(out["prompts"], (8, 16), strict=False) if p - a >= 1.0]
    if len(out["prompts"]) != 2 or late:
        bad.append(f"prompts {out['prompts']}")
    return _case("band", bad)


def plank() -> Case:
    spans = [[4, 8, "sag"], [12, 15, "pike"], [20, 24, "sag"], [28, 31, "pike"], [35, 39, "sag"]]
    out = _many([("plankSession", {"hold": 45, "faults": spans, "wobble": 3, "seed": 9}),
                 ("plankSession", {"hold": 60, "wobble": 3, "seed": 10})])  # fmt: skip
    bad = []
    t0, t1 = out[0]["tally"] or {}, out[1]["tally"] or {}
    if abs(t0.get("hold_s", -9) - 45) > 1 or abs(t1.get("hold_s", -9) - 60) > 1:
        bad.append(f"holds {t0.get('hold_s')} {t1.get('hold_s')}")
    if t0.get("sags", 0) + t0.get("pikes", 0) < 0.9 * len(spans) or t1.get("sags", 0) + t1.get(
        "pikes", 0
    ):
        bad.append(f"spans {t0} / false {t1}")
    return _case("plank", bad)


def space() -> Case:
    out = _many([("spaceCheck", {"things": things}) for things, _w in SPACE])
    bad = []
    for (_t, want), r in zip(SPACE, out, strict=True):
        texts = [w.get("text", "") for w in r["view"]]
        ok = (
            f"Not clear: move the {want}." in texts
            if want
            else "Clear: nothing in your space to trip on or hit." in texts
        )
        if not ok or r["tally"] is not None:
            bad.append(f"want {want or 'clear'}: {texts}")
    return _case("space", bad)


POINTY = ("points", "point", "x", "y", "box", "frame", "image")


def tallies() -> Case:
    bad = []
    for use, r in STATE["kept"]:
        t = r.get("tally")
        if t is None:
            continue
        if parse_tally(use, t) is None:
            bad.append(f"{use}: {json.dumps(t)[:80]}")
        if any(k in t for k in POINTY):
            bad.append(f"{use} holds a point: {sorted(t)}")
    return _case("tallies", bad)


def not_medical() -> Case:
    bad = [f"{use}: {w}" for use, r in STATE["kept"] for w in r["view"]
           for v in w.values() if isinstance(v, str) and medical_hits(v)]  # fmt: skip
    return _case("not_medical", bad)


CASES: tuple[Callable[[], Case], ...] = (reps, half_reps, form, warm_up, band, plank, space)


def cases() -> list[Case]:
    STATE["kept"] = []
    return [c() for c in CASES] + [tallies(), not_medical()]


@contextmanager
def _copy(name: str, old: str, new: str) -> Iterator[None]:
    with tempfile.TemporaryDirectory() as tmp:
        for f in STATIC.glob("console-coach-*.js"):
            shutil.copy(f, Path(tmp) / f.name)
        path = Path(tmp) / name
        text = path.read_text(encoding="utf-8")
        if old not in text:
            raise RuntimeError(f"the control's line is not in {name}: {old}")
        path.write_text(text.replace(old, new), encoding="utf-8")
        STATE["base"] = tmp
        try:
            yield
        finally:
            STATE["base"] = None


@contextmanager
def _plant(fn: Callable[[dict[str, Any]], dict[str, Any]]) -> Iterator[None]:
    STATE["plant"] = fn
    try:
        yield
    finally:
        STATE["plant"] = None


def _with_point(r: dict[str, Any]) -> dict[str, Any]:
    return dict(r, tally=dict(r["tally"], points=[[0.5, 0.5]])) if r.get("tally") else r


def _with_medical(r: dict[str, Any]) -> dict[str, Any]:
    return dict(
        r,
        view=[*r["view"], {"kind": "line", "text": "Your blood pressure is in the normal range."}],
    )


HALF = (
    "squat: Object.freeze({ down: 110, up: 160 })",
    "squat: Object.freeze({ down: 140, up: 160 })",
)
CONTROLS: tuple[tuple[str, Callable[[], Any], str], ...] = (
    ("half_counts", lambda: _copy("console-coach-reps.js", *HALF), "strength:half_reps"),
    ("point_in_tally", lambda: _plant(_with_point), "strength:tallies"),
    ("medical_view", lambda: _plant(_with_medical), "strength:not_medical"),
    (
        "faint_things",
        lambda: _copy("console-coach-space.js", "const SCORE = 0.4;", "const SCORE = 0;"),
        "strength:space",
    ),
)


def control() -> dict[str, Any]:
    """Each control must make its own case fail; `suite_failed` is True only if every one did."""
    failed: list[str] = []
    held: list[str] = []
    for name, ctx, case in CONTROLS:
        with ctx():
            results = {r["id"]: r for r in cases()}
        (failed if not results[case]["passed"] else held).append(name)
    return {"suite_failed": not held, "failed_cases": failed, "held": held}


def main() -> int:
    results = cases()
    for r in results:
        print(
            ("PASS " if r["passed"] else "FAIL ")
            + r["id"]
            + ("" if r["passed"] else f"  {r['failures']}")
        )
    ctl = control()
    print(
        ("PASS " if ctl["suite_failed"] else "FAIL ")
        + f"controls: failed {ctl['failed_cases']} held {ctl['held']}"
    )
    return 0 if all(r["passed"] for r in results) and ctl["suite_failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
