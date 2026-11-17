# evals/r13_1/run.py
"""R13.1 eval -- "Try-on: the 3D figure and See it on me" (plan docs/plans/r13-1-try-on.md "Tests
and evals"), one suite file per part so each builder fills only its own:

    python evals/r13_1/run.py --mock [--part figure --part looks ...]

    figure.py    B  the manifest's sums, licences and the 3.5 MB budget; the measure table (each
                    measurement alone within 0.5 cm, the others within 3.5 cm, quantised within
                    0.2 cm); the private zone covered in every layer state x slot set x variant x
                    view; AVT-07's geometry; tuck and open; triangles; the GLB reader's refusals.
                    Controls: two morphs swapped; `waist_down` dropped; the base shorts dropped
                    in "All"; the blazer sleeve 2 cm longer
    looks.py     A  AVT-03, 04, 05, 09 (with the race and D20), 11, 14, OPS-05. Controls: the
                    private filter off; the fresh check off; `lock` without D20's check
    seeme.py     C  through the PORT (C's adapter on recorded answers and I0's one-garment fake):
                    consent, the cap (the 34th fits, the 35th not), 10 presses at once, billed or
                    not, text parts read nowhere, private pieces refused, No-AI, bearer tokens,
                    the end date, `price_changed`, `request_id`. Controls: a read-then-write
                    reserve; the consent check off; the private check in the console only; the ₹
                    hashed into the consent
    console.py   D  each row's UI half in the browser; the checklist under every failure; the YES
                    dialog; the ₹ confirm's Cancel sends nothing; the caption; 44 px; day and
                    night. Control: the engine stub with the checklist hook removed
    e2e.py       I1 the workbook's end-to-end tests (the avatar halves) and See it on me's life.
                    Control: the look built from a stale view
    needles.py   I1 his photo, a picture, his measurements, the consent text, a private piece,
                    the token, Google's text part: searched in every sink. Control: the adapter
                    logging its request body
    contract.py  I0 (BUILT) six parts build through the real wiring and own only their routes,
                    services, collections, Privacy rows and job; a broken R13.1 part is "setup
                    failed" while R13's four still run and R13's Wardrobe rows still read; the
                    Try-on section has its stand-ins. Control: the contract check off (a stray
                    route, row, service or `data` is accepted)

Every part file exposes PART, BUILT, `async def cases() -> list[dict]` (each {"id":
"<part>:<case>", "passed", "failures"}) and `async def control() -> dict` ({"name",
"suite_failed", "failed_cases"}: its cases re-run with its negative control applied). Each row's
own control (the plan's M8 table) is a case of its part's control run.

STAGED (plan seam 15): until I1 an unbuilt part reports "<part>:not_built_yet" and PASSES
(`STUBS_PASS = True`), so `make eval-mock` stays green on every part branch; I1 sets
`STUBS_PASS = False` (a stub never reads as green) and `tests/test_r131_seams.py` pins the flip
from then on. The suite passes when every case passes AND every BUILT part's control made that
part fail (a suite that cannot fail proves nothing). Gated in `evals/run_all_mock.py` after R13.
No real Google call is ever made here.
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
for _p in (HERE.parent, ROOT / "tests", ROOT / "src"):  # appended: no evals/r13_1 on sys.path
    if str(_p) not in sys.path:
        sys.path.append(str(_p))
from r1d_common import finish  # noqa: E402

PARTS = ("figure", "looks", "seeme", "console", "e2e", "needles", "contract")
STUBS_PASS = True  # until I1 (pinned by tests/test_r131_seams.py; I1 flips it and the pin)


def load(part: str) -> ModuleType | None:
    """The part's module, by path under a unique name (no clash with R13's `contract`)."""
    path = HERE / f"{part}.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(f"r13_1_{part}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _missing(part: str) -> dict[str, Any]:
    return {"id": f"{part}:missing", "passed": False, "failures": [f"evals/r13_1/{part}.py"]}


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
    return finish(HERE, "r13_1", results, combined(controls, parts))


if __name__ == "__main__":
    sys.exit(main())
