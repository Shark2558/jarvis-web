# evals/r8_1/dynamic.py
"""R8.1 eval, builder G (`dynamic`, BUILT): the dynamic workout coaches' pass bars
(docs/plans/r8-vision.md v8.0.4 sections 2.2 and 8), on synthetic data only --
tests/fixtures/r8/dynamic_sequences.mjs (Node: the console's real use-case modules). No public
dataset is used, so none needs a licence here.

    python evals/r8_1/dynamic.py          runs the cases and the controls; exit 1 on a failure

Cases (each {"id": "dynamic:<case>", "passed", "failures"}):
  boxing          row 228: punch counts within 1 per 20 at 30 and 15 frames a second; types right
                  on >= 85 % at 30; marked "about" at 15 (and not at 30)
  agility         row 230: every split within 0.2 s of the exact gate crossing; none missed
  jump            row 235: height within 5 cm at 30 frames a second, 10 cm (and "about") at 15;
                  stiff and knees-in landings flagged on >= 90 %, soft ones never
  handstand_gate  row 237: no hold is timed or kept without a wall or a spotter confirmed
  handstand       row 237: hold time within 1 s; the hips past the limit cue "Come down now."
  kettlebell      row 239: swings within 1 per 20 (a part swing never counts); hinge versus
                  squat right on >= 90 %
  tallies         every tally the sessions made fits its model (kept), and none holds a point
  not_medical     no view any session made says anything medical (jarvis.coach.words)

Negative controls (each must make its case fail, or the suite proves nothing):
  no_gate          the handstand coach takes a wall for granted (a module copy)
  types_never_about  the boxing coach never marks its types "about" (a module copy)
  frame_flight     the jump height from the airborne frames' span alone (a module copy)
  half_swings      the kettlebell coach counts a swing that stops at the belly (a module copy)
  point_in_tally   a tally carries a body point
  medical_view     a view says "You have a knee disorder."
"""

from __future__ import annotations

import asyncio
import math
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

PART = "dynamic"
BUILT = True
SEQ = FIXTURES / "dynamic_sequences.mjs"

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


def _per_20(n: int) -> int:
    return max(1, math.ceil(n / 20))


def boxing() -> Case:
    bad: list[str] = []
    same = total = 0
    for fps, seed, lead in ((30, 1, "left"), (30, 2, "right"), (15, 3, "left"), (15, 4, "right")):
        out = _node("boxingSession", {"fps": fps, "seed": seed, "lead": lead, "punches": 50})
        truth, got = len(out["truth"]), out["tally"]["punches"]
        bad += (
            [f"{fps} fps seed {seed}: {got} of {truth}"]
            if abs(got - truth) > _per_20(truth)
            else []
        )
        if out["tally"]["about"] is not (fps < 25):
            bad.append(f"{fps} fps: about is {out['tally']['about']}")
        if fps == 30:
            match = run_node(SEQ, "mod.matchPunches", out["seen"], out["truth"])
            same, total = same + match["sameType"], total + truth
        _keep("boxing", out)
    if same / max(1, total) < 0.85:
        bad.append(f"types right {same}/{total}")
    return _case("boxing", bad)


def agility() -> Case:
    bad: list[str] = []
    for marks, fps, seed in (("line", 15, 1), ("shuttle", 10, 2), ("box", 15, 3)):
        out = _node("agilityRun", {"marks": marks, "fps": fps, "seed": seed, "runs": 3})
        if len(out["measured"]) != len(out["truth"]):
            bad.append(f"{marks}: {len(out['measured'])} runs of {len(out['truth'])}")
            continue
        for run, truth in zip(out["measured"], out["truth"], strict=True):
            bad += [
                f"{marks} {fps} fps: {a:.2f} s vs {b:.2f} s"
                for a, b in zip(run, truth, strict=False)
                if abs(a - b) > 0.2
            ]
        _keep("agility", out)
    return _case("agility", bad)


def jump() -> Case:
    bad: list[str] = []
    heights = [0.1, 0.2, 0.3, 0.4, 0.5]
    for fps, limit in ((30, 5), (15, 10)):
        out = _node("jumpSession", {"fps": fps, "heights": heights, "seed": fps})
        if len(out["seen"]) != len(heights):
            bad.append(f"{fps} fps: {len(out['seen'])} jumps of {len(heights)}")
        bad += [
            f"{fps} fps: {g['cm']:.1f} cm vs {t['cm']:.1f} cm"
            for g, t in zip(out["seen"], out["truth"], strict=False)
            if abs(g["cm"] - t["cm"]) > limit
        ]
        if out["tally"]["about"] is not (fps < 25):
            bad.append(f"{fps} fps: about is {out['tally']['about']}")
        _keep("jump", out)
    kinds = ["soft", "stiff", "in", "stiff", "in", "soft", "stiff", "in", "soft", "in"]
    out = _node("jumpSession", {"heights": [0.25] * len(kinds), "landings": kinds})
    hit = sum(
        (t["kind"] == "stiff" and g["stiff"]) or (t["kind"] == "in" and g["kneesIn"])
        for g, t in zip(out["seen"], out["truth"], strict=True)
    )
    flagged = kinds.count("stiff") + kinds.count("in")
    bad += [f"landings flagged {hit}/{flagged}"] if hit / flagged < 0.9 else []
    bad += [
        f"a soft landing flagged at {t['land']:.1f} s"
        for g, t in zip(out["seen"], out["truth"], strict=True)
        if t["kind"] == "soft" and (g["stiff"] or g["kneesIn"])
    ]
    _keep("jump", out)
    return _case("jump", bad)


def handstand_gate() -> Case:
    bad: list[str] = []
    for setup in (None, {}, {"support": "nobody"}):
        out = _node("handstandSession", {"holds": [15], "setup": setup})
        if out["tally"] is not None or out["holds"]:
            bad.append(f"timed without a wall or a spotter: {setup}")
        _keep("handstand", out)
    return _case("handstand_gate", bad)


def handstand() -> Case:
    bad: list[str] = []
    holds = [5, 12, 30]
    for support in ("wall", "spotter"):
        out = _node("handstandSession", {"holds": holds, "setup": {"support": support}})
        if abs(out["best"] - max(holds)) > 1 or abs(out["last"] - holds[-1]) > 1:
            bad.append(f"{support}: holds {out['best']:.1f}, {out['last']:.1f} s")
        bad += [f"{support}: a cue with no drift"] if out["drifts"] else []
        _keep("handstand", out)
    drift = {"hold": 0, "at": 4, "amount": 0.25}
    out = _node("handstandSession", {"holds": [15], "setup": {"support": "wall"}, "drift": drift})
    if out["drifts"] != 1 or out["overAt"] is None or out["overAt"] - out["passAt"] > 1:
        bad.append(f"drift: {out['drifts']} cues at {out['overAt']} (passed {out['passAt']:.1f})")
    _keep("handstand", out)
    return _case("handstand", bad)


def kettlebell() -> Case:
    bad: list[str] = []
    right = total = 0
    for seed, fps in ((1, 15), (2, 10), (3, 15)):
        squats, partial = [2, 7, 13, 19], [4, 10, 16]
        out = _node(
            "kettlebellSession",
            {"seed": seed, "fps": fps, "swings": 24, "squats": squats, "partial": partial},
        )
        truth, got = len(out["truth"]), out["tally"]["swings"]
        bad += (
            [f"seed {seed}: {got} swings of {truth}"] if abs(got - truth) > _per_20(truth) else []
        )
        if len(out["styles"]) == truth:
            right += sum(a == b for a, b in zip(out["styles"], out["truth"], strict=True))
            total += truth
        _keep("kettlebell", out)
    if right / max(1, total) < 0.9:
        bad.append(f"hinge versus squat right {right}/{total}")
    return _case("kettlebell", bad)


def tallies() -> Case:
    bad = [
        f"{use}: {sorted(t or {})}"
        for use, t in KEPT
        if t is not None and parse_tally(use, t) is None
    ]
    bad += [
        f"{use} holds a point"
        for use, t in KEPT
        if t and any(k in t for k in ("points", "point", "box", "frame"))
    ]
    bad += [] if any(t for _, t in KEPT) else ["no tally was made"]
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
    boxing,
    agility,
    jump,
    handstand_gate,
    handstand,
    kettlebell,
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
        for path in STATIC.glob("console-coach-*.js"):
            shutil.copy(path, Path(tmp) / path.name)
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
def _plant(key: str, value: Any) -> Iterator[None]:
    PLANT[key] = value
    try:
        yield
    finally:
        PLANT.clear()


def _one(name: str, old: str, new: str) -> Callable[[], Any]:
    return lambda: _copies({f"console-coach-{name}.js": (old, new)})


def _controls() -> list[tuple[str, Callable[[], Any], Callable[[], Case]]]:
    gate = "return null;\n  const limit"
    return [
        (
            "no_gate",
            _one("handstand", gate, "return { support: 'wall', limit: LIMIT };\n  const limit"),
            handstand_gate,
        ),
        (
            "types_never_about",
            _one("boxing", "const FAST_FPS = 25;", "const FAST_FPS = 0;"),
            boxing,
        ),
        (
            "frame_flight",
            _one(
                "jump",
                "return Number.isFinite(exact) && Math.abs(exact - rough) < 0.1 ? exact : rough;",
                "return last.t - first.t;",
            ),
            jump,
        ),
        (
            "half_swings",
            _one("kettlebell", "{ down: -0.8, up: -0.55 }", "{ down: -1.0, up: -0.95 }"),
            kettlebell,
        ),
        (
            "point_in_tally",
            lambda: _plant("point", [0.41, 0.52]),
            lambda: (handstand(), tallies())[1],
        ),
        (
            "medical_view",
            lambda: _plant("line", "You have a knee disorder."),
            lambda: (jump(), not_medical())[1],
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
        "name": "six controls: " + ", ".join(n for n, _, _ in _controls()),
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
