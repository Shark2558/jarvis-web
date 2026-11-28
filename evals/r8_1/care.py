# evals/r8_1/care.py
"""R8.1 eval, builder H (`care`, BUILT): the partner, walk, sit-to-stand and meal coaches' pass
bars (docs/plans/r8-vision.md v8.0.4 sections 2.2 and 8), on synthetic data only:
tests/fixtures/r8/tests_sequences.mjs (Node: the console's real use-case modules, and for row 240
the real port core too). No public dataset is used, so none needs a licence here.

    python evals/r8_1/care.py            runs the cases and the controls; exit 1 on a failure

Cases (each {"id": "care:<case>", "passed", "failures"}):
  partner          row 240: his ranges within 10 degrees, holds within 1 s, the hold phase F1 >= 0.9
  partner_privacy  row 240: every state kept for the partner is the empty "not-you" one, its view
                   shows no number and keeps no tally, his results are the same whatever the partner
                   does, and the same through the real driver
  consent          row 240: nothing starts before the consent tap, or long after it
  walk             row 263: laps exact and turns counted, side on and end on; distance = laps x
                   the course length
  sit_stand        row 269: the 30-second count exact (with partial stands and the halfway edge) and
                   the five-times time within 0.3 s
  meal             row 247: bites within 10 %, the meal's length within a minute, another person in
                   view pauses the count
  labels           rows 263, 269: "Practice, not a clinical test." and "Stop if anything hurts."
  tallies          every tally the sessions made fits its model (kept), and none holds a point
  not_medical      no view any session made says anything medical (jarvis.coach.words)

Negative controls (each must make its case fail, or the suite proves nothing):
  partner_kept     the partner rule takes any body in the consent window for him (a module copy)
  no_pause         the meal counter never pauses for another person in view (a module copy)
  half_stands      the sit-to-stand counter takes a partial rise as a stand (a module copy)
  point_in_tally   a tally carries a body point
  medical_view     a view says "You have a heart condition: take your tablet."
"""

from __future__ import annotations

import asyncio
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
from jarvis.coach.words import STOP, medical_hits  # noqa: E402

PART = "care"
BUILT = True
SEQ = FIXTURES / "tests_sequences.mjs"
NOT_YOU = '{"kind":"not-you"}'
NOT_CLINICAL = "Practice, not a clinical test."
STRETCHES = [
    {"joint": "hip", "peak": 72, "hold": 15},
    {"joint": "knee", "peak": 118, "hold": 10, "deepen": 6},
    {"joint": "shoulder", "peak": 150, "hold": 20},
]

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
    if tally is not None:
        KEPT.append((use, tally))
    VIEWS.append(view)


def _case(name: str, failures: list[str]) -> Case:
    return {"id": f"{PART}:{name}", "passed": not failures, "failures": failures[:8]}


def _texts(view: list[dict[str, Any]]) -> list[str]:
    return [str(v) for w in view for k, v in w.items() if k != "kind" and isinstance(v, str)]


def partner() -> Case:
    bad: list[str] = []
    for seed in (1, 2):
        out = _node("partnerSession", {"seed": seed, "partner": "wild", "stretches": STRETCHES})
        _keep("partner-stretch", out)
        done, truths = out["done"] or [], out["truths"]
        if len(done) != len(truths):
            bad.append(f"seed {seed}: {len(done)} stretches for {len(truths)}")
        for got, want in zip(done, truths, strict=False):
            if abs(got["range"] - want["range"]) > 10 or abs(got["hold"] - want["hold"]) > 1:
                bad.append(f"seed {seed}: {got} for {want}")
        h = out["hold"]
        f1 = 2 * h["tp"] / max(1, 2 * h["tp"] + h["fp"] + h["fn"])
        if f1 < 0.9:
            bad.append(f"seed {seed}: hold F1 {f1:.3f}")
    return _case("partner", bad)


def partner_privacy() -> Case:
    bad: list[str] = []
    runs = {p: _node("partnerSession", {"seed": 3, "partner": p, "stretches": STRETCHES})
            for p in ("none", "still", "wild")}  # fmt: skip
    for p in ("still", "wild"):
        out = runs[p]
        if out["partnerStates"] != [NOT_YOU] or out["partnerHoldsNumbers"]:
            bad.append(f"{p}: the partner's states {out['partnerStates'][:3]}")
        if out["partnerTally"] is not None or out["partnerViewHasNumber"]:
            bad.append(f"{p}: the partner's tally or view shows something")
    if not runs["none"]["done"] == runs["still"]["done"] == runs["wild"]["done"]:
        bad.append("his stretches change with what the partner does")
    real = _node("partnerDriver", {"seed": 4, "partner": "wild"})
    by_track = {t["track"]: t for t in real["tallies"]}
    if real["errors"] or real["partnerStates"] != [NOT_YOU] or 1 not in by_track:
        bad.append(f"the real driver: {real['errors']} {real['partnerStates'][:3]}")
    elif by_track[1]["tally"] is not None or any(
        ch.isdigit() for ch in json.dumps(by_track[1]["view"])
    ):
        bad.append(f"the real driver shows the partner: {by_track[1]}")
    if 0 not in by_track or not by_track[0]["tally"]:
        bad.append("the real driver kept nothing of his stretch")
    else:
        _keep("partner-stretch", by_track[0])
    return _case("partner_privacy", bad)


def consent() -> Case:
    bad: list[str] = []
    for opts in ({"consent": False}, {"consentAt": -120}, {"partnerAt": 0}):
        out = _node("partnerSession", {"seed": 5, "stretches": STRETCHES[:1], **opts})
        _keep("partner-stretch", out)
        if out["tally"] is not None or out["partnerHoldsNumbers"]:
            bad.append(f"{opts}: started ({out['kind']})")
    return _case("consent", bad)


def walk() -> Case:
    bad: list[str] = []
    for opts in (
        {"seed": 1, "course": 8, "lengthS": 6, "turnS": 1.2},
        {"seed": 2, "course": 4, "lengthS": 3.5, "turnS": 0.9, "fps": 6, "drop": 9},
        {"seed": 3, "view": "end", "course": 5, "lengthS": 4.2, "turnS": 1.0, "noise": 0.0015},
        {"seed": 4, "ends": "at-end"},
    ):
        out = _node("walkSession", opts)
        _keep("walk-test", out)
        tally, truth = out["tally"] or {}, out["truth"]
        if (tally.get("laps"), tally.get("turns")) != (truth["laps"], truth["turns"]):
            bad.append(f"{opts}: {tally.get('laps')}/{tally.get('turns')} for {truth}")
        elif abs(tally["metres"] - truth["laps"] * tally["course_m"]) > 0.05:
            bad.append(f"{opts}: {tally['metres']} m")
    return _case("walk", bad)


def sit_stand() -> Case:
    bad: list[str] = []
    for opts in (
        {"seed": 1, "rise": 0.8},
        {"seed": 2, "rise": 1.4, "fps": 10},
        {"seed": 3, "partial": [2, 3, 6], "partialPeak": 140},
        {"seed": 4, "edge": "above"},
        {"seed": 5, "edge": "below"},
    ):
        out = _node("sitStandSession", opts)
        _keep("sit-to-stand", out)
        tally, truth = out["tally"] or {}, out["truth"] or {}
        if tally.get("in_30s") != truth.get("in30"):
            bad.append(f"{opts}: {tally.get('in_30s')} stands for {truth.get('in30')}")
        if abs(tally.get("five_s", -9) - truth.get("five", 9)) > 0.3:
            bad.append(f"{opts}: five in {tally.get('five_s')} s for {truth.get('five')}")
    return _case("sit_stand", bad)


def meal() -> Case:
    bad: list[str] = []
    for opts in (
        {"seed": 1, "gapS": 25},
        {"seed": 2, "gapS": 15, "dwell": 0.35},
        {"seed": 3, "others": [[120, 300]]},
        {"seed": 3, "others": [[120, 300]], "target": "me"},
    ):
        out = _node("mealSession", opts)
        _keep("meal", out)
        tally, truth = out["tally"] or {}, out["truth"]
        if abs(tally.get("bites", 0) - truth["bites"]) > 0.1 * truth["bites"]:
            bad.append(f"{opts}: {tally.get('bites')} bites for {truth['bites']}")
        if abs(tally.get("minutes", 0) - truth["minutes"]) > 1:
            bad.append(f"{opts}: {tally.get('minutes')} minutes for {truth['minutes']:.1f}")
        if opts.get("others") and not all(
            any(w["kind"] == "paused" for w in v) for v in out["pausedViews"] or [[]]
        ):
            bad.append(f"{opts}: not paused while someone else was in view")
    return _case("meal", bad)


def labels() -> Case:
    bad: list[str] = []
    for call, opts in (("walkSession", {"seed": 6}), ("sitStandSession", {"seed": 6})):
        texts = _texts(_node(call, opts)["view"])
        if NOT_CLINICAL not in texts or STOP not in texts:
            bad.append(f"{call}: {texts}")
    return _case("labels", bad)


def tallies() -> Case:
    bad = [f"{use}: {sorted(t or {})}" for use, t in KEPT if parse_tally(use, t) is None]
    bad += [
        f"{use} holds a point"
        for use, t in KEPT
        if t
        and (
            any(k in t for k in ("points", "point", "box"))
            or any(isinstance(v, (dict, list)) for v in t.values())
        )
    ]
    return _case("tallies", bad)


def not_medical() -> Case:
    lines = [line for view in VIEWS for line in _texts(view)]
    return _case(
        "not_medical", [f"{line!r}: {medical_hits(line)}" for line in lines if medical_hits(line)]
    )


SUITE: tuple[Callable[[], Case], ...] = (
    partner,
    partner_privacy,
    consent,
    walk,
    sit_stand,
    meal,
    labels,
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
def _plant(key: str, value: Any) -> Iterator[None]:
    PLANT[key] = value
    try:
        yield
    finally:
        PLANT.clear()


PARTNER_RULE = "if (r.who !== 'me' || !inWindow(r)) return NOT_YOU;"
MEAL_PAUSE = (
    "const paused = (s, t) => !s.alone || s.poseT === null || t - s.poseT > STALE_S;",
    "const paused = () => false;",
)
HALF_STANDS = ("const STAND = 160;", "const STAND = 130;")


def _controls() -> list[tuple[str, Callable[[], Any], Callable[[], Case]]]:
    return [
        (
            "partner_kept",
            lambda: _copies(
                {"console-coach-partner.js": (PARTNER_RULE, "if (!inWindow(r)) return NOT_YOU;")}
            ),
            partner_privacy,
        ),
        ("no_pause", lambda: _copies({"console-coach-meal.js": MEAL_PAUSE}), meal),
        ("half_stands", lambda: _copies({"console-coach-sitstand.js": HALF_STANDS}), sit_stand),
        (
            "point_in_tally",
            lambda: _plant("point", [{"x": 0.5, "y": 0.4}]),
            lambda: (walk(), tallies())[1],
        ),
        (
            "medical_view",
            lambda: _plant("line", "You have a heart condition: take your tablet."),
            lambda: (labels(), walk(), not_medical())[2],
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
