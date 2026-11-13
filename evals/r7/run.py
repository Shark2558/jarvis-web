# evals/r7/run.py
"""R7 eval -- "Mobile, watch and phone camera" (plan docs/plans/r7-mobile.md "Tests and evals per
part"), one suite file per part so each builder fills only its own:

    python evals/r7/run.py --mock [--part shell --part vision ...]

    shell.py     A  the manifest; launch words only open a screen (do=talk never starts the mic);
                    the share tray asks nothing before a press; push targets reach the open window
    vision.py    B  only the camera's door asks for a camera; no picture bytes leave during a look;
                    results outside their schema are dropped; "cameras off" locks and never unlocks
    phone.py     C  the link code's rules; every vector verifies, every bad request is a bare 401;
                    the door reaches no /v1 route; the app lock and its five 423 readers
    body.py      D  watch intake ranges, sleep sums, one writer a night; SOS joins, sends, caps, its
                    own test budget, no coordinate anywhere; the Telegram hook
    needles.py   I1 after a day on fakes no coordinate, heart value, contact number, read text or
                    pixel pattern is in any document, log, address, audit line, alert or reply
    contract.py  I0 (BUILT) the phone's signed request: every shared vector's string, header,
                    signature and payload bytes; its control flips one byte of every good body

Every part file exposes:

    PART: str        its name (the file's stem)
    BUILT: bool      False while it is the I0 stub
    async def cases() -> list[dict]       each {"id": "<part>:<case>", "passed", "failures"}
    async def control() -> dict           {"name", "suite_failed", "failed_cases"}: the part's
                                          cases re-run with its negative control applied

An unbuilt part reports one passing case "<part>:not_built_yet" and is not asked for a control.
The suite passes when every case passes AND every BUILT part's control made that part fail (a
suite that cannot fail proves nothing). Gated in `make eval-mock` (evals/run_all_mock.py) from I0.
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

PARTS = ("shell", "vision", "phone", "body", "needles", "contract")


def load(part: str) -> ModuleType | None:
    """The part's module, by path under a unique name (no clash with any other `vision`)."""
    path = HERE / f"{part}.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(f"r7_{part}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _missing(part: str) -> dict[str, Any]:
    return {"id": f"{part}:missing", "passed": False, "failures": [f"evals/r7/{part}.py"]}


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
    return finish(HERE, "r7", results, combined(controls, parts))


if __name__ == "__main__":
    sys.exit(main())
