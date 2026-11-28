# evals/r8/engine.py
"""R8 eval, builder A (`engine`): row 216, the vision engine on the device (docs/plans/r8-vision.md
2.1, 4.2, 4.8, D4, D7, D9; ROWS.md: "A rep count runs with the Wi-Fi off."). Mock only: the real
console-vision.js and console-vision-r8.js run in Node on tests/fixtures/r8/engine.mjs (a fake
MediaPipe, a fake browser whose canvases hold real pixels, FAKE model files and their sums), and
the seven-segment reader reads synthetic displays. No real model, picture or person.

    pinned_files_only   pose, hands and digits load, each model only from /static/vendor/vision/
                        and only with the bytes SUMS8 pins (a changed file is "not installed")
    tracks_follow       two people crossing keep their tracks (D6: everyone in view)
    wifi_off_reps       ten squats counted on the live driver with the network gone; no request
    setup_test          frames a second, a look's milliseconds and the share of one core, from a
                        tap-started look; nothing sent; full pose kept only where it keeps 15/s
    digits_read         monitor screens (builder D's kind) through the pane's rule: >= 95 % right,
                        none wrong; plain displays >= 92 %, none sure and wrong; varied ones (slant,
                        turn, blur, ghosts, LED, small lines): >= 85 %, <= 2 % sure and wrong

Negative control (it must fail the cases named): every model file served changed (pinned_files_only
fails) and the reader's last digit changed (digits_read fails).

Exposes the R7 part protocol (evals/r7/run.py): PART, BUILT, async cases(), async control(). Run
alone: `python evals/r8/engine.py` (exit 1 when a case fails or the control passes).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))
from r8_fakes import FIXTURES, run_node  # noqa: E402

PART = "engine"
BUILT = True
ENGINE = FIXTURES / "engine.mjs"
TAMPERED = {
    "r7-1/pose_landmarker_lite.task": "changed",
    "r8-1/hand_landmarker.task": "changed",
    "r8-1/pose_landmarker_full.task": "changed",
}


def _run(name: str, **given: Any) -> Any:
    return run_node(ENGINE, f"mod.{name}", given)


def _case(case: str, failures: list[str]) -> dict[str, Any]:
    return {"id": f"{PART}:{case}", "passed": not failures, "failures": failures}


def pinned_files_only(files: dict[str, str] | None = None) -> list[str]:
    out = _run("loads", files=files or {})
    bad = [
        f"{t}: {out['out'][t]}" for t in ("pose", "hands", "digits") if not out["out"][t].get("ok")
    ]
    bad += [f"fetched {u}" for u in out["fetches"] if not u.startswith("/static/vendor/vision/")]
    changed = _run("loads", files={"r8-1/hand_landmarker.task": "changed"})["out"]["hands"]
    if changed.get("error") != "not installed":
        bad.append(f"a changed hand model loaded: {changed}")
    return bad


def tracks_follow() -> list[str]:
    results = _run("poseFrames", script="crossing", frames=24)["results"]
    hips = [
        next(b for b in r["data"]["bodies"] if b["track"] == 0)["points"][23]["x"] for r in results
    ]
    return [] if hips == sorted(hips) and hips[-1] > 0.7 else [f"track 0 did not follow: {hips}"]


def wifi_off_reps() -> list[str]:
    out = _run("repsOffline", reps=10)
    bad = [f"counted {out['count']} of 10"] if out["count"] != 10 else []
    if out["fetched_offline"] or out["errors"]:
        bad.append(f"offline requests {out['fetched_offline']}, errors {out['errors']}")
    return bad


def setup_test() -> list[str]:
    out = _run("setupTest", tasks=["pose", "hands"], opts={"seconds": 1})
    r, bad = out["result"] or {}, []
    if out["error"] or not 10 <= r.get("fps", 0) <= 16 or out["sent"]:
        bad.append(f"setup test: {out}")
    elif (
        abs(r["core"] - sum(r["tasks"][t]["fps"] * r["tasks"][t]["ms"] / 1000 for t in r["tasks"]))
        > 0.01
    ):
        bad.append(f"core share is not frame time x rate: {r}")
    slow = _run(
        "setupTest", opts={"seconds": 1, "model": "full"}, slow={"FAKE pose full model": 60}
    )
    if (slow["result"] or {}).get("model") != "lite":
        bad.append(f"a slow full model was kept: {slow}")
    return bad


def digits_read(mutate: str = "") -> list[str]:
    bad = []
    screens = _run("monitors", n=240, seed=41, mutate=mutate)
    if screens["right"] < 228 or screens["wrong"]:
        bad.append(f"monitor screens: {screens['right']}/240 right, {screens['wrong']} wrong")
    plain = _run("accuracy", n=60, plain=True, seed=7, mutate=mutate)
    if plain["right"] < 55 or plain["sure_wrong"]:
        bad.append(
            f"plain displays: {plain['right']}/60 right, {plain['sure_wrong']} sure and wrong"
        )
    varied = _run("accuracy", n=100, seed=11, mutate=mutate)
    if varied["right"] < 85 or varied["sure_wrong"] > 2:
        bad.append(
            f"varied displays: {varied['right']}/100 right, {varied['sure_wrong']} sure and wrong"
        )
    return bad


async def cases() -> list[dict[str, Any]]:
    return [
        _case("pinned_files_only", pinned_files_only()),
        _case("tracks_follow", tracks_follow()),
        _case("wifi_off_reps", wifi_off_reps()),
        _case("setup_test", setup_test()),
        _case("digits_read", digits_read()),
    ]


async def control() -> dict[str, Any]:
    failed = [
        name
        for name, failures in (
            ("pinned_files_only", pinned_files_only(TAMPERED)),
            ("digits_read", digits_read("last-digit")),
        )
        if failures
    ]
    name = "every model file changed; the reader's last digit changed"
    return {"name": name, "suite_failed": len(failed) == 2, "failed_cases": failed}


def main() -> int:
    results = asyncio.run(cases())
    ctl = asyncio.run(control())
    print(json.dumps({"cases": results, "control": ctl}, indent=1))
    return 0 if all(r["passed"] for r in results) and ctl["suite_failed"] else 1


if __name__ == "__main__":
    sys.exit(main())
