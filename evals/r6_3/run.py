# evals/r6_3/run.py
"""R6.3 eval -- "The Build Book: written by AI, short tour and full book" (plan
docs/plans/r6-3-book-content.md "Tests and evals"), one suite file per part so each builder fills
only its own:

    python evals/r6_3/run.py --mock [--part facts --part writer ...]

    facts.py     A  --check twice identical with facts.json; every tour key known; the module map
                    has all 73 cards once; the index (paths, symbols, constants); the counter on a
                    fixture; the inventory; the scrubber's new kinds; scrubbed paths (H6); 31
                    services (M7); the route list against the built app (M9). Controls: a set
                    iterated unsorted; the IP pattern removed; C69 out of the map; a raw path; a
                    router name dropped
    writer.py    B  through jarvis.llm with the fake brains: zero calls before YES, exactly YES, the
                    trial cap (Rs 100: 5 holds of Rs 16.71 through, the 6th refused before it is
                    sent), holds, the 80 % gate, the clocks (H7, M3), the checks and the precision
                    case (H5), the pages vault and the free carry (H3, M4, M5), the grants (H2), the
                    offer (M2). Controls: the plan's `writer` row
    console.py   C  the trial, the pick's YES boxes, the first write's YES, Update, Stop, the Full
                    book, continue, 44 px, both widths, day and night. Control: the YES box sending
                    "yes"
    tour.py      D  both bands, his seven highlights, both running-example lines, no doubled word,
                    the approved words byte for byte, a guest's tour with no Rs, no T16 and no
                    owner-only line (speak through the real route: 404), 17 scenes in 2D, 3D and
                    Motion Off, each picture's data (M6). Controls: T13's owner line in a guest's
                    tour, the audience ignored, a highlight dropped, 290 words a minute, T12's facts
                    without a group
    needles.py   I1 the creator name, his e-mail, a vault text, a memory fact, a mail subject, a
                    fake secret, the canary, the handle in a path, a stand-in for each hashed word:
                    never in a pack, prompt, page, draft, trial page, facts.json, log, audit, notice
                    or export
    e2e.py       I1 the trial, the pick, the first write, a page in the reader; a new release ->
                    update_ready -> Update -> only the changed pages; a guest's tour
    contract.py  I0 (BUILT) the writer builds through its one join, owns only its 13 routes (503
                    not_built_yet until B), `book_write` rides the clocks and does nothing without a
                    run; 47ee8fc's book loads unchanged; R6's sealing files untouched (M4). Controls
                    (I0's own, L12): the stub job calling the fake brain once; a stray route

Every part file exposes PART, BUILT, `async def cases() -> list[dict]` (each {"id":
"<part>:<case>", "passed", "failures"}) and `async def control() -> dict` ({"name",
"suite_failed", "failed_cases"}: its cases re-run with its negative control applied). Each row's
own control (the plan's "A control for every row's own case") is a case of its part's control run.

STAGED (plan seam 12): until I1 an unbuilt part reports "<part>:not_built_yet" and PASSES
(`STUBS_PASS = True`), so `make eval-mock` stays green on every part branch; I1 sets
`STUBS_PASS = False` (a stub never reads as green) and `tests/test_r63_seams.py` pins the flip
from then on. The suite passes when every case passes AND every BUILT part's control made that
part fail (a suite that cannot fail proves nothing). Gated in `evals/run_all_mock.py` after R13.1.
No real model is ever called here.
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
for _p in (HERE.parent, ROOT / "tests", ROOT / "src"):  # appended: no evals/r6_3 on sys.path
    if str(_p) not in sys.path:
        sys.path.append(str(_p))
from r1d_common import finish  # noqa: E402

PARTS = ("facts", "writer", "console", "tour", "needles", "e2e", "contract")
STUBS_PASS = False  # I1: every part is built; a stub never reads as green (pinned)


def load(part: str) -> ModuleType | None:
    """The part's module, by path under a unique name (no clash with R13's or R13.1's)."""
    path = HERE / f"{part}.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(f"r6_3_{part}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _missing(part: str) -> dict[str, Any]:
    return {"id": f"{part}:missing", "passed": False, "failures": [f"evals/r6_3/{part}.py"]}


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
    return finish(HERE, "r6_3", results, combined(controls, parts))


if __name__ == "__main__":
    sys.exit(main())
