# evals/r8/coaches.py
"""R8 eval, builder D (`coaches`, BUILT): the desk coaches' pass bars (docs/plans/r8-vision.md
v8.0.4 sections 2.1 and 8), on synthetic data only -- tests/fixtures/r8/desk_sequences.mjs (Node:
the console's real use-case modules) and tests/fixtures/r8/desk_home.py (the home camera's rules).
No public dataset is used, so none needs a licence here.

    python evals/r8/coaches.py            runs the cases and the controls; exit 1 on a failure

Cases (each {"id": "coaches:<case>", "passed", "failures"}):
  reaction      row 224: >= 95 % of touches counted; every reaction time within 100 ms
  breath        row 238: the pacer exact at every rhythm; the rate within 1 a minute, 6 to 20
  water         row 248: >= 90 % of sips counted; at most 1 false sip a synthetic hour
  bp_reading    row 262: >= 95 % of 300 synthetic monitor screens read right by the engine's
                `digits` reader, none wrong (builder A's; joined at I1, so a missing reader fails)
  bp_rule       row 262: the pane's proposal rule is the server's (never a line under 0.8)
  bp_checklist  row 262: each checklist item judged right on >= 90 % of synthetic poses
  seated        row 227: reps within 1 per set of 10 for each move; the next set adapts
  rehab         row 268: counts within 1 per 10; range of motion within 10 degrees
  reach         row 276: reach time within 150 ms; the same sequence, the same score
  tallies       every tally the sessions made fits its model (kept), and none holds a point
  not_medical   no view any session made says anything medical (jarvis.coach.words)

Negative controls (each must make its case fail, or the suite proves nothing):
  half_reps        the seated rule counts both halves of a swing (a coach that counts half reps)
  point_in_tally   a tally carries a body point
  medical_view     a view says "Your blood pressure is in the normal range."
  guessing_rule    the pane proposes a reading from lines read with any certainty (a module copy)
  no_dwell         the water counter takes a cup passing the lips as a sip (a copy of the module)
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import random
import shutil
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / "src", ROOT / "tests"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from r8_fakes import FIXTURES, STATIC, run_node  # noqa: E402

from jarvis.coach.bp import proposal_from_digits  # noqa: E402
from jarvis.coach.home import seated as seated_rule  # noqa: E402
from jarvis.coach.home.bp_posture import BpPostureCoach, BpPostureState  # noqa: E402
from jarvis.coach.home.seated import Block, SeatedCoach, SeatedState  # noqa: E402
from jarvis.coach.usecases import parse_tally  # noqa: E402
from jarvis.coach.words import medical_hits  # noqa: E402

PART = "coaches"
BUILT = True
SEQ = FIXTURES / "desk_sequences.mjs"
_spec = importlib.util.spec_from_file_location("r8_eval_desk_home", FIXTURES / "desk_home.py")
assert _spec is not None and _spec.loader is not None
H: ModuleType = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(H)

Case = dict[str, Any]
BASE: dict[str, str] = {}  # a control's directory of changed module copies (empty: the real ones)
PLANT: dict[str, Any] = {}  # a control's planted tally key or view line
KEPT: list[tuple[str, dict[str, Any] | None]] = []
VIEWS: list[list[dict[str, Any]]] = []


def _node(call: str, opts: dict[str, Any]) -> Any:
    extra = {"base": BASE["dir"]} if "dir" in BASE else {}
    return run_node(SEQ, f"mod.{call}", {**opts, **extra})


def _keep(use: str, out: dict[str, Any]) -> None:
    tally = dict(out["tally"]) if out.get("tally") else None
    if tally is not None and "point" in PLANT:
        tally["points"] = PLANT["point"]
    view = list(out.get("view") or [])
    if "line" in PLANT:
        view.append({"kind": "line", "text": PLANT["line"]})
    KEPT.append((use, tally))
    VIEWS.append(view)


def _case(name: str, failures: list[str]) -> Case:
    return {"id": f"{PART}:{name}", "passed": not failures, "failures": failures[:8]}


def reaction() -> Case:
    bad: list[str] = []
    hits = touches = 0
    for seed in (1, 2, 3):
        out = _node("reactionGame", {"seed": seed, "skip": [7], "noise": 0.003})
        truths = [t for t in out["truths"] if t is not None]
        touches, hits = touches + len(truths), hits + out["hits"]
        bad += [
            f"seed {seed}: {m} ms vs {t} ms"
            for m, t in zip(out["rts"], truths, strict=False)
            if abs(m - t) > 100
        ]
        _keep("reaction-game", out)
    if hits / max(1, touches) < 0.95:
        bad.append(f"touches counted {hits}/{touches}")
    return _case("reaction", bad)


def breath() -> Case:
    bad: list[str] = []
    for rhythm in ("4-4", "4-7-8", "box", "6-a-minute", "5-5"):
        out = _node("breathSession", {"rhythm": rhythm, "seconds": 30, "perMinute": 9})
        bad += [f"{rhythm}: {out['mismatches']} pacer frames off"] if out["mismatches"] else []
    for per in (6, 10, 14, 20):
        out = _node("breathSession", {"perMinute": per, "noise": 0.0025, "seed": per})
        got = out["tally"]["per_minute"]
        bad += [f"{per} a minute read {got}"] if abs(got - per) > 1 else []
        _keep("breath", out)
    return _case("breath", bad)


def water() -> Case:
    bad: list[str] = []
    counted = truth = 0
    for seed in (1, 2):
        events = run_node(SEQ, "mod.waterEvents", {"seed": seed})
        out = _node("waterDay", {"seconds": 3600, "events": events, "seed": seed, "hidden": 0.3})
        counted, truth = counted + min(out["tally"]["sips"], out["truth"]), truth + out["truth"]
        false = out["tally"]["sips"] - out["truth"]
        bad += [f"seed {seed}: {false} false sips in the hour"] if false > 1 else []
        _keep("water", out)
    if counted / max(1, truth) < 0.9:
        bad.append(f"sips counted {counted}/{truth}")
    none = _node(
        "waterDay",
        {
            "seconds": 3600,
            "seed": 8,
            "events": run_node(SEQ, "mod.waterEvents", {"sips": 0, "others": 40, "seed": 8}),
        },
    )
    bad += (
        [f"{none['tally']['sips']} sips in an hour with none"] if none["tally"]["sips"] > 1 else []
    )
    return _case("water", bad)


def bp_reading() -> Case:
    out = _node("bpDisplays", {"n": 300, "seed": 91})
    if "skipped" in out:  # R8 I1: the engine's reader is joined; without it the case fails
        return _case("bp_reading", [str(out["skipped"])])
    bad = [f"read right {out['right']}/{out['n']}"] if out["right"] / out["n"] < 0.95 else []
    bad += [f"read wrong {out['wrong']}: {json.dumps(out['misses'][:3])}"] if out["wrong"] else []
    return _case("bp_reading", bad)


RULE_CASES = (
    [(128, 0.97), (82, 0.95), (71, 0.9)],
    [(128, 0.97), (82, 0.5), (71, 0.9)],
    [(128, 0.97), (82, 0.79), (71, 0.9)],
    [(82, 0.97), (128, 0.95), (71, 0.9)],
    [(128, 0.97), (82, 0.95)],
)


def bp_rule() -> Case:
    """The pane's proposal rule is the server's: a line read under 0.8 is never proposed."""
    module = (
        Path(BASE["dir"]) / "console-coach-bp.js"
        if "dir" in BASE
        else STATIC / "console-coach-bp.js"
    )
    bad = []
    for lines in RULE_CASES:
        js = run_node(module, "mod.proposal", [{"value": v, "score": sc} for v, sc in lines])
        py = proposal_from_digits(lines)
        if js != (py.model_dump() if py else None):
            bad.append(f"{lines}: the pane proposes {js}, the server {py}")
    return _case("bp_rule", bad)


FAULT_ITEM = {
    "lean": "back",
    "feet": "feet",
    "crossed": "legs",
    "arm_low": "arm",
    "arm_hang": "arm",
}


def bp_checklist() -> Case:
    coach = BpPostureCoach()
    right = dict.fromkeys(("back", "feet", "legs", "arm"), 0)
    n = 200
    for i in range(n):
        rnd = random.Random(500 + i)
        fault = rnd.choice([None, *FAULT_ITEM])
        pts = H.bp_body([fault] if fault else [], noise=0.003, rng=random.Random(i), vary=rnd)
        one = coach.on_result(H.result("pose", {"points": pts}, 0.0), None)
        for item in right:
            right[item] += one.checks[item] == (FAULT_ITEM.get(fault or "") != item)
    state: BpPostureState | None = None
    for r in H.bp_frames(305, []):
        state = coach.on_result(r, state)
    out = coach.summary(state)
    _keep("bp-posture", dict(out))
    bad = [f"{k} right on {v}/{n}" for k, v in right.items() if v / n < 0.9]
    bad += (
        []
        if out["tally"] and out["tally"]["score"] == 100
        else ["five still minutes did not tick every line"]
    )
    return _case("bp_checklist", bad)


def seated() -> Case:
    coach, bad = SeatedCoach(), []
    state: SeatedState | None
    for move in H.SWINGS:
        state, counts = None, []
        for r in H.seated_session(move, [10, 10], noise=0.003, seed=7):
            before: Block | None = state.blocks.get(move) if state else None
            state = coach.on_result(r, state)
            after = state.blocks.get(move)
            if after is not None and after != before:
                counts.append(after.reps - (before.reps if before else 0))
        bad += (
            [f"{move}: sets of 10 counted {counts}"]
            if len(counts) != 2 or any(abs(c - 10) > 1 for c in counts)
            else []
        )
        _keep("seated", dict(coach.summary(state)))
    state, targets = None, []
    for r in H.seated_session("arm_raise", [6, 10, 10]):
        before = state.blocks.get("arm_raise") if state else None
        state = coach.on_result(r, state)
        after = state.blocks.get("arm_raise")
        if after is not None and after != before:
            targets.append(after.target)
    bad += (
        []
        if targets == [8, 8, 10]
        else [f"targets after 6, 10, 10 reps: {targets} (want 8, 8, 10)"]
    )
    return _case("seated", bad)


def rehab() -> Case:
    bad: list[str] = []
    for exercise in ("open_close", "finger_tap", "thumb_to_finger"):
        out = _node("rehabSession", {"exercise": exercise, "noise": 0.003, "peak": 60, "rest": 5})
        t, truth = out["tally"], out["truth"]
        bad += (
            [f"{exercise}: {t['reps']} reps of {truth['reps']}"]
            if abs(t["reps"] - truth["reps"]) > 1
            else []
        )
        if truth["range"] is not None and abs(t["range_deg"] - truth["range"]) > 10:
            bad.append(f"{exercise}: range {t['range_deg']} vs {truth['range']:.1f}")
        _keep("hand-rehab", out)
    return _case("rehab", bad)


def reach() -> Case:
    bad: list[str] = []
    one = _node("reachSession", {"seed": 31})
    two = _node("reachSession", {"seed": 31})
    bad += [
        f"{m} ms vs {t} ms"
        for m, t in zip(one["trials"], one["truths"], strict=False)
        if m is None or abs(m - t) > 150
    ]
    bad += [] if one["tally"] == two["tally"] else ["the same sequence scored twice differently"]
    _keep("reach-grasp", one)
    return _case("reach", bad)


def tallies() -> Case:
    bad = [
        f"{use}: {sorted(t or {})}" for use, t in KEPT if t is None or parse_tally(use, t) is None
    ]
    bad += [
        f"{use} holds a point"
        for use, t in KEPT
        if t and any(k in t for k in ("points", "point", "box", "frame"))
    ]
    return _case("tallies", bad)


def not_medical() -> Case:
    lines = [
        str(v)
        for view in VIEWS
        for w in view
        for k, v in w.items()
        if k != "kind" and isinstance(v, str)
    ]
    return _case(
        "not_medical", [f"{line!r}: {medical_hits(line)}" for line in lines if medical_hits(line)]
    )


SUITE: tuple[Callable[[], Case], ...] = (
    reaction,
    breath,
    water,
    bp_reading,
    bp_checklist,
    seated,
    rehab,
    reach,
)


def _run() -> list[Case]:
    KEPT.clear()
    VIEWS.clear()
    out = [fn() for fn in SUITE]
    return [*out, tallies(), not_medical()]


async def cases() -> list[Case]:
    return await asyncio.to_thread(_run)


# ---- negative controls --------------------------------------------------------------------------
@contextmanager
def _copies(changes: dict[str, tuple[str, str]]) -> Iterator[None]:
    """The real modules copied to a temporary directory with one line changed in each named one."""
    with tempfile.TemporaryDirectory() as tmp:
        for f in ("console-coach-geom.js", *(p.name for p in STATIC.glob("console-coach-*.js"))):
            shutil.copy(STATIC / f, Path(tmp) / f)
        for name, (old, new) in changes.items():
            path = Path(tmp) / name
            text = path.read_text(encoding="utf-8")
            if old not in text:
                raise RuntimeError(f"the control's line is not in {name}: {old}")
            path.write_text(text.replace(old, new), encoding="utf-8")
        BASE["dir"] = tmp
        try:
            yield
        finally:
            BASE.clear()


@contextmanager
def _half_reps() -> Iterator[None]:
    real = seated_rule.Swing.step

    def both(self: Any, t: float, raw: float, move: Any) -> Any:
        out = real(self, t, raw, move)
        return replace(out, count=out.count + (1 if out.phase != self.phase and self.phase else 0))

    setattr(seated_rule.Swing, "step", both)  # noqa: B010 - the control swaps the method back after
    try:
        yield
    finally:
        setattr(seated_rule.Swing, "step", real)  # noqa: B010


@contextmanager
def _plant(key: str, value: Any) -> Iterator[None]:
    PLANT[key] = value
    try:
        yield
    finally:
        PLANT.clear()


def _controls() -> list[tuple[str, Callable[[], Any], Callable[[], Case]]]:
    return [
        ("half_reps", _half_reps, seated),
        ("point_in_tally", lambda: _plant("point", [0.41, 0.52]), lambda: (reach(), tallies())[1]),
        (
            "medical_view",
            lambda: _plant("line", "Your blood pressure is in the normal range."),
            lambda: (reach(), not_medical())[1],
        ),
        (
            "guessing_rule",
            lambda: _copies(
                {"console-coach-bp.js": ("READ_MIN_SCORE = 0.8;", "READ_MIN_SCORE = 0;")}
            ),
            bp_rule,
        ),
        (
            "no_dwell",
            lambda: _copies(
                {"console-coach-water.js": ("const MIN_DWELL_S = 0.5;", "const MIN_DWELL_S = -1;")}
            ),
            water,
        ),
    ]


def _control() -> dict[str, Any]:
    failed: list[str] = []
    held: list[str] = []
    for name, ctx, case in _controls():
        KEPT.clear()
        VIEWS.clear()
        with ctx():
            result = case()
        (failed if not result["passed"] else held).append(f"{name} -> {result['id']}")
    return {
        "name": "five controls: " + ", ".join(n for n, _, _ in _controls()),
        "suite_failed": not held,
        "failed_cases": failed,
        "held": held,
    }


async def control() -> dict[str, Any]:
    return await asyncio.to_thread(_control)


def main() -> int:
    results = asyncio.run(cases())
    for r in results:
        print(
            ("PASS " if r["passed"] else "FAIL ")
            + r["id"]
            + ("" if r["passed"] else f"  {r['failures']}")
        )
    ctl = asyncio.run(control())
    print(
        ("PASS " if ctl["suite_failed"] else "FAIL ")
        + f"controls: failed {ctl['failed_cases']} held {ctl['held']}"
    )
    return 0 if all(r["passed"] for r in results) and ctl["suite_failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
