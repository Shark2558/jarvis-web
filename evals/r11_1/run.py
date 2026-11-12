# evals/r11_1/run.py
"""R11.1 eval -- "Your observations, fixed" (plan docs/plans/r11-1-observations.md "Tests and
evals per part"), one suite file per part so each builder fills only its own:

    python evals/r11_1/run.py --mock [--part plan --part files ...]

    plan.py    A  a long plan with a CSV ends in ONE card or a real answer, never a filler; an
                  empty or cut-off answer is retried once and never stored; 60 sessions are one
                  card, one approval, per-item results and one Undo; a skipped session moves the
                  rest and drops none; the inbox summary counts every category and masks codes
    files.py   B  spoken Indian English is understood ("D csb file" -> "the CSV file") or one
                  short question is asked, with no model call in No-AI mode; xlsx / xls / pptx /
                  pictures / zip / folder are read inside their caps or refused in plain words;
                  the rupee estimate comes before a paid reply on a large file
    photos.py  C  2,000 picked photos import in the background and resume; the bridge's photo
                  routes answer ids only; a face group named once is recognised afterwards; a
                  child needs a guardian's yes; nothing but ids reaches the cloud
    look.py    D  a picture of a thing, place, label or logo is researched; a picture of a
                  person is described and NEVER identified; profile cards open one tab a click;
                  the Vitals rows name the failing part and the GitHub token is read at connect

Every part file exposes:

    PART: str        its name (the file's stem)
    BUILT: bool      False while it is the I0 stub
    async def cases() -> list[dict]       each {"id": "<part>:<case>", "passed", "failures"}
    async def control() -> dict           {"name", "suite_failed", "failed_cases"}: the part's
                                          cases re-run with its negative control applied

An unbuilt part reports one passing case "<part>:not_built_yet" and is not asked for a control.
The suite passes when every case passes AND every BUILT part's control made that part fail (a
suite that cannot fail proves nothing). I1 adds it to `make eval-mock` (evals/run_all_mock.py).
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

PARTS = ("plan", "files", "photos", "look")


def load(part: str) -> ModuleType | None:
    """The part's module, by path under a unique name (no clash with any other `gate`)."""
    path = HERE / f"{part}.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(f"r11_1_{part}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _missing(part: str) -> dict[str, Any]:
    return {"id": f"{part}:missing", "passed": False, "failures": [f"evals/r11_1/{part}.py"]}


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
        "suite_failed": all(bool(c["suite_failed"]) for c in controls.values()),  # none built: True
        "failed_cases": {p: controls[p]["failed_cases"] for p in built},
        "parts_not_built": [p for p in parts if p not in controls],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="the only mode (CI)")
    ap.add_argument("--part", action="append", choices=PARTS, help="run only these parts")
    args = ap.parse_args()
    logging.getLogger().setLevel(logging.INFO)
    parts = tuple(args.part or PARTS)
    results, controls = asyncio.run(run_parts(parts))
    return finish(HERE, "r11_1", results, combined(controls, parts))


if __name__ == "__main__":
    sys.exit(main())
