# evals/r8_1/flow.py
"""R8.1 eval, builder F (`flow`, BUILT): the flow and balance coaches' pass bars
(docs/plans/r8-vision.md v8.0.4 sections 2.2 and 8), on synthetic data only --
tests/fixtures/r8/flow_sequences.mjs (Node: the console's real use-case modules). No public dataset
is used, so none needs a licence here.

    python evals/r8_1/flow.py            runs the cases and the controls; exit 1 on a failure

Cases (each {"id": "flow:<case>", "passed", "failures"}):
  yoga        row 221: each pose of the list recognised on >= 90 % of synthetic holds; every
              recognised hold timed within 1 s
  balance     row 226: hold time within 1 s; the one-leg state's F1 >= 0.95; the sway score rises
              with every step of injected sway; the same stand gives the same tally
  pilates     row 231: >= 90 % of steps recognised, each held within 1 s; every out-of-order step
              in the fixtures reported (counted and marked)
  tai_chi     row 232: steps against his recorded reference with F1 >= 0.9 at three tempos; the
              smoothness score lower for every sequence with injected jerks
  dance       row 236: in time >= 80 in each of four styles; a 0.5 s offset (late or early) drops
              the sync score by >= 20 in each; in-time scores within 10 across styles
  tallies     every tally the sessions made fits its model (kept), and none holds a point; every
              recording fits the routine store (angles only)
  not_medical no view any session made says anything medical (jarvis.coach.words)

Negative controls (each must make its case fail, or the suite proves nothing):
  sway_blind      the balance coach's sway reference made huge (every stand scores 0)
  any_order       the Pilates coach never finds a step out of order (a module copy)
  flick_blind     the tai-chi coach's flick limits made huge (a module copy)
  timing_blind    the dance coach's timing costs nothing (a module copy)
  point_in_tally  a tally carries a body point
  medical_view    a view says "You may have a balance disorder."
"""

from __future__ import annotations

import asyncio
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

from jarvis.coach.store import Routine  # noqa: E402
from jarvis.coach.usecases import parse_tally  # noqa: E402
from jarvis.coach.words import medical_hits  # noqa: E402

PART = "flow"
BUILT = True
SEQ = FIXTURES / "flow_sequences.mjs"
YOGA = (
    *("mountain", "tree", "warrior_i", "warrior_ii", "triangle", "chair", "cobra", "child"),
    *("downward_dog", "bridge", "cat_cow", "seated_forward_bend"),
)
STYLES = ("lyrical", "pop", "bhangra", "classical")

Case = dict[str, Any]
BASE: dict[str, str] = {}  # a control's directory of changed module copies (empty: the real ones)
PLANT: dict[str, Any] = {}  # a control's planted tally key or view line
KEPT: list[tuple[str, dict[str, Any] | None]] = []
VIEWS: list[list[dict[str, Any]]] = []
ROUTINES: list[tuple[str, list[list[float]]]] = []


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


def yoga() -> Case:
    bad: list[str] = []
    right: dict[str, int] = dict.fromkeys(YOGA, 0)
    seeds = (1, 2, 3, 4)
    for seed in seeds:
        out = _node(
            "yogaSession",
            {
                "poses": list(YOGA),
                "seed": seed,
                "tilt": (-4, 0, 3, 4)[seed % 4],
                "flip": seed % 2 == 0,
                "hold": 6 + seed,
            },
        )
        for m in out["matched"]:
            if m["got"] == m["pose"]:
                right[m["pose"]] += 1
                if abs(m["got_s"] - m["truth_s"]) > 1.0:
                    bad.append(f"{m['pose']}: held {m['got_s']} s of {m['truth_s']} s")
        _keep("yoga", out)
    bad += [
        f"{p}: {n}/{len(seeds)} holds recognised" for p, n in right.items() if n / len(seeds) < 0.9
    ]
    return _case("yoga", bad)


def balance() -> Case:
    bad: list[str] = []
    for stand, front, seed in (("left", False, 1), ("right", True, 2)):
        out = _node(
            "balanceSession",
            {
                "stand": stand,
                "front": front,
                "seed": seed,
                "seconds": 34,
                "holds": [[2.0, 14.5], [18.0, 31.0]],
                "sway": 1.5,
            },
        )
        bad += [
            f"{stand}: held {g['s']} s of {t} s"
            for g, t in zip(out["log"], out["truth"], strict=False)
            if abs(g["s"] - t) > 1.0
        ]
        bad += [f"{stand}: {len(out['log'])} holds"] if len(out["log"]) != 2 else []
        bad += [f"{stand}: F1 {out['f1']:.2f}"] if out["f1"] < 0.95 else []
        _keep("balance", out)
    scores = [
        _node("balanceSession", {"sway": s, "seed": 5})["tally"]["sway"] for s in (0, 1, 2, 4)
    ]
    if not all(b > a for a, b in zip(scores, scores[1:], strict=False)):
        bad.append(f"sway scores {scores} do not rise with the sway")
    again = [_node("balanceSession", {"sway": 2, "seed": 7})["tally"] for _ in range(2)]
    bad += ["the same stand gave two tallies"] if again[0] != again[1] else []
    return _case("balance", bad)


def pilates() -> Case:
    bad: list[str] = []
    found = total = 0
    for seed in (1, 2):
        out = _node("pilatesSession", {"seed": seed, "hold": 4 + seed})
        total += len(out["truth"])
        found += len(out["log"])
        bad += [
            f"{g['step']}: held {g['s']} s of {t['s']} s"
            for g, t in zip(out["log"], out["truth"], strict=False)
            if g["step"] == t["step"] and abs(g["s"] - t["s"]) > 1.0
        ]
        _keep("pilates", out)
    if found / max(1, total) < 0.9:
        bad.append(f"steps recognised {found}/{total}")
    for order in (
        ["hundred", "roll_up", "single_leg_stretch", "leg_circle", "spine_stretch"],
        ["hundred", "swan", "roll_up", "leg_circle", "shoulder_bridge", "teaser"],
    ):
        out = _node("pilatesSession", {"steps": order, "seed": 5})
        marks = next(w for w in out["view"] if w["kind"] == "checklist")["items"]
        flagged = sum(1 for i in marks if i["ok"] is False)
        if (
            not out["tally"]
            or out["tally"]["out_of_order"] != len(out["wrong"])
            or flagged != len(out["wrong"])
        ):
            bad.append(f"{order}: {out['tally']} for {out['wrong']} out of order")
        _keep("pilates", out)
    return _case("pilates", bad)


def tai_chi() -> Case:
    bad: list[str] = []
    rec = _node("taichiSession", {"mode": "record", "seed": 11})
    rows = run_node(SEQ, "mod.rowsOf", rec)
    ROUTINES.append(("tai-chi", rows))
    for tempo, seed in ((1.0, 1), (0.8, 2), (1.25, 3)):
        out = _node("taichiSession", {"reference": rows, "tempo": tempo, "seed": seed})
        done = [m["step"] for m in out["marks"] if m["done"]]
        tp = len([s for s in done if s in out["performed"]])
        fp, fn = len(done) - tp, len(out["performed"]) - tp
        if out["steps"] != 8 or 2 * tp / max(1, 2 * tp + fp + fn) < 0.9:
            bad.append(f"tempo {tempo}: {out['steps']} steps, marks {out['marks']}")
        _keep("tai-chi", out)
    last = _node("taichiSession", {"reference": rows, "seed": 6})["tally"]["smooth"]
    for jerks in ([9.0], [9.0, 21.0], [5.0, 11.0, 17.0, 23.0]):
        got = _node("taichiSession", {"reference": rows, "seed": 6, "jerks": jerks})["tally"][
            "smooth"
        ]
        bad += [f"{len(jerks)} jerks scored {got}, not under {last}"] if got >= last else []
        last = got
    return _case("tai_chi", bad)


def dance() -> Case:
    bad: list[str] = []
    synced: list[int] = []
    for style in STYLES:
        rec = _node("danceSession", {"mode": "record", "style": style, "seed": 21, "routine": 2})
        rows = run_node(SEQ, "mod.rowsOf", rec)
        ROUTINES.append(("dance", rows))
        _keep("dance-record", {"tally": None, "view": rec["view"]})
        play = {"style": style, "reference": rows, "routine": 2}
        sync = _node("danceSession", {**play, "seed": 22})
        synced.append(sync["tally"]["sync"])
        bad += (
            [f"{style}: in time scored {sync['tally']['sync']}"]
            if sync["tally"]["sync"] < 80
            else []
        )
        for offset in (0.5, -0.5):
            off = _node("danceSession", {**play, "seed": 23, "offset": offset})
            drop = sync["tally"]["sync"] - off["tally"]["sync"]
            bad += [f"{style}: {offset:+} s dropped {drop}"] if drop < 20 else []
            _keep("dance", off)
        _keep("dance", sync)
    if max(synced) - min(synced) > 10:
        bad.append(f"in-time scores across styles {synced}")
    return _case("dance", bad)


def tallies() -> Case:
    bad = [
        f"{use}: {sorted(t or {})}"
        for use, t in KEPT
        if use != "dance-record" and (t is None or parse_tally(use, t) is None)
    ]
    bad += [
        f"{use} holds a point"
        for use, t in KEPT
        if t and any(k in t for k in ("points", "point", "box", "frame"))
    ]
    for kind, rows in ROUTINES:
        try:
            routine = Routine.model_validate({"kind": kind, "angles": rows})
        except ValueError as exc:
            bad.append(f"{kind} recording refused: {str(exc)[:80]}")
            continue
        bad += (
            [f"{kind} rows are not nine angles"] if {len(r) for r in routine.angles} != {9} else []
        )
    return _case("tallies", bad)


def not_medical() -> Case:
    lines = [
        str(v)
        for view in VIEWS
        for w in view
        for k, v in w.items()
        if k != "kind" and isinstance(v, str)
    ]
    lines += [
        str(i.get("text"))
        for view in VIEWS
        for w in view
        for i in w.get("items") or []
        if isinstance(i, dict)
    ]
    return _case(
        "not_medical", [f"{line!r}: {medical_hits(line)}" for line in lines if medical_hits(line)]
    )


SUITE: tuple[Callable[[], Case], ...] = (yoga, balance, pilates, tai_chi, dance)


def _run() -> list[Case]:
    KEPT.clear()
    VIEWS.clear()
    ROUTINES.clear()
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


def _controls() -> list[tuple[str, Callable[[], Any], Callable[[], Case]]]:
    one = "console-coach-"
    return [
        (
            "sway_blind",
            lambda: _copies(
                {one + "balance.js": ("const SWAY_REF = 0.08;", "const SWAY_REF = 1e9;")}
            ),
            balance,
        ),
        (
            "any_order",
            lambda: _copies({one + "pilates.js": ("late = k < s.far;", "late = false;")}),
            pilates,
        ),
        (
            "flick_blind",
            lambda: _copies(
                {
                    one + "taichi.js": (
                        "const FLICK_ONE = 11;\nconst FLICK_TWO = 7;",
                        "const FLICK_ONE = 1e9;\nconst FLICK_TWO = 1e9;",
                    )
                }
            ),
            tai_chi,
        ),
        (
            "timing_blind",
            lambda: _copies(
                {one + "dance.js": ("const TIMING_PTS = 60;", "const TIMING_PTS = 0;")}
            ),
            dance,
        ),
        (
            "point_in_tally",
            lambda: _plant("point", [0.41, 0.52]),
            lambda: (balance(), tallies())[1],
        ),
        (
            "medical_view",
            lambda: _plant("line", "You may have a balance disorder."),
            lambda: (balance(), not_medical())[1],
        ),
    ]


def _control() -> dict[str, Any]:
    failed: list[str] = []
    held: list[str] = []
    for name, ctx, case in _controls():
        KEPT.clear()
        VIEWS.clear()
        ROUTINES.clear()
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
