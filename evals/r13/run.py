# evals/r13/run.py
"""R13 eval -- "Wardrobe & laundry, phone first" (plan docs/plans/r13-wardrobe.md "Tests and
evals"), one suite file per part so each builder fills only its own:

    python evals/r13/run.py --mock [--part catalog --part laundry ...]

    catalog.py   A  INV-01-17, OPS-03, OPS-06; controls: candidates off (INV-05 fails), the dedup
                    off (INV-08 and OPS-03 fail)
    laundry.py   B  LND-01-15, OPS-02; control: holds off (LND-03, LND-04, OPS-02 fail)
    styling.py   C  STY-01-17, LND-16, OPS-04; controls: the availability check off (STY-10,
                    STY-15, STY-16 fail), the wear rule off (STY-13, STY-15's "sends nothing")
    phone.py     D  D20's sentences with zero provider calls and R14's phrases unchanged; D10's
                    views; OPS-01's refusals; control: the person check off (OPS-01 fails)
    e2e.py       I1 the workbook's end-to-end tests 1-5, 7 and 8 (its pass line); controls: the
                    fold in arrival order (1 and 3 fail), a planted bad suggestion (8 fails)
    needles.py   I1 one simulated week; every sink searched for every needle class; control:
                    the model view swapped for the panel view (the private-label cases fail)
    contract.py  I0 (BUILT) every part builds through the real wiring and owns only its tools,
                    jobs, services and routes; a stray part is refused; control: no check

Every part file exposes PART, BUILT, `async def cases() -> list[dict]` (each {"id":
"<part>:<case>", "passed", "failures"}) and `async def control() -> dict` ({"name",
"suite_failed", "failed_cases"}: its cases re-run with its negative control applied).

STAGED (plan seam 15, review M11): until I1 an unbuilt part reports "<part>:not_built_yet" and
PASSES (`STUBS_PASS = True`, the R7 and R11 runners' rule before their I1s), so `make eval-mock`
stays green on every branch while the parts are built. I1 sets `STUBS_PASS = False` (R14's rule:
a stub never reads as green) and `tests/test_r13_seams.py` pins the flip from then on. The suite
passes when every case passes AND every BUILT part's control made that part fail (a suite that
cannot fail proves nothing). Gated in `make eval-mock` (evals/run_all_mock.py) from I0.
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

PARTS = ("catalog", "laundry", "styling", "phone", "e2e", "needles", "contract")
STUBS_PASS = True  # I0 to I1: an unbuilt part passes; I1 sets False (pinned by the seam test)


def load(part: str) -> ModuleType | None:
    """The part's module, by path under a unique name (no clash with any other `catalog`)."""
    path = HERE / f"{part}.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(f"r13_{part}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _missing(part: str) -> dict[str, Any]:
    return {"id": f"{part}:missing", "passed": False, "failures": [f"evals/r13/{part}.py"]}


async def run_parts(
    parts: tuple[str, ...], *, stubs_pass: bool = STUBS_PASS
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    results: list[dict[str, Any]] = []
    controls: dict[str, Any] = {}
    for part in parts:
        module = load(part)
        if module is None:
            results.append(_missing(part))
            continue
        got = await module.cases()
        if not module.BUILT and not stubs_pass:  # after I1 a stub's own word is never a pass
            got = [{**c, "passed": False, "failures": ["not built"]} for c in got]
        results.extend(got)
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
        "stubs_pass": STUBS_PASS,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="the only mode (CI)")
    ap.add_argument("--part", action="append", choices=PARTS, help="run only these parts")
    args = ap.parse_args()
    logging.getLogger().setLevel(logging.INFO)
    parts = tuple(args.part or PARTS)
    results, controls = asyncio.run(run_parts(parts))
    return finish(HERE, "r13", results, combined(controls, parts))


if __name__ == "__main__":
    sys.exit(main())
