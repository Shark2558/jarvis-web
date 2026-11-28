# evals/r8/run.py
"""R8 eval -- "Vision at the desk" (plan docs/plans/r8-vision.md v8.0.4 sections 2.1 and 8), one
suite file per builder's part, joined at I1 (docs/plans/r8-integration/I1-NOTES.md):

    python evals/r8/run.py --mock [--part engine --part home ...]

    engine.py    A  pose v2 with tracks, hands, the seven-segment reader (>= 95 % read, none
                    wrong), the setup test's numbers, the pinned models' manifests
    cameras.py   B  the off switches and "never" rooms, "cameras off" never touching the alarm,
                    the no-cloud check (private addresses only, both stages), camera health
    desk.py      C  rows 181-183: posture (a slouch held 60 s, and the workbook's 10 minutes), the
                    day strip on a synthetic 8-hour day, screen time per program
    coaches.py   D  the desk coaches (224, 227, 238, 248, 262, 268, 276), the AHA table, the
                    reading rule, every tally fits its model, no view says anything medical
    home.py      J  the home laptop's loop: no frame, point or box in any report; who is who; the
                    tracking target; "cameras off" stops the stream; the rate

Every part file exposes PART, BUILT, `async def cases()` and `async def control()`, the R7
runner's interface (evals/r7/run.py). The suite passes when every case passes AND every part's
negative control made that part fail (a suite that cannot fail proves nothing). Gated in `make
eval-mock` (evals/run_all_mock.py) from I1. No network, no camera, no real person's data.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import logging
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))
from r1d_common import finish  # noqa: E402

PARTS = ("engine", "cameras", "desk", "coaches", "home")


def load(part: str) -> ModuleType | None:
    """The part's module, by path under a unique name (no clash with another suite's files)."""
    path = HERE / f"{part}.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(f"r8_{part}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _missing(part: str) -> dict[str, Any]:
    return {"id": f"{part}:missing", "passed": False, "failures": [f"evals/r8/{part}.py"]}


async def run_parts(parts: tuple[str, ...]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    results: list[dict[str, Any]] = []
    controls: dict[str, Any] = {}
    for part in parts:
        module = load(part)
        if module is None:
            results.append(_missing(part))
            continue
        results.extend(await module.cases())
        if module.BUILT:
            controls[part] = await module.control()
    return results, controls


def combined(controls: dict[str, Any], parts: tuple[str, ...]) -> dict[str, Any]:
    built = sorted(controls)
    return {
        "name": " + ".join(c["name"] for c in controls.values()) or "none: no part is built yet",
        "suite_failed": bool(controls) and all(bool(c["suite_failed"]) for c in controls.values()),
        "failed_cases": {p: controls[p]["failed_cases"] for p in built},
        "parts_not_built": [p for p in parts if p not in controls],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="the only mode (CI)")
    ap.add_argument("--part", action="append", choices=PARTS, help="run only these parts")
    args = ap.parse_args()
    logging.getLogger().setLevel(logging.WARNING)
    parts = tuple(args.part or PARTS)
    results, controls = asyncio.run(run_parts(parts))
    return finish(HERE, "r8", results, combined(controls, parts))


if __name__ == "__main__":
    sys.exit(main())
