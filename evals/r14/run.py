# evals/r14/run.py
"""R14 eval -- "Free hardening" (plan docs/plans/r14-hardening.md "Per item"), one suite file per
part so each builder fills only its own:

    python evals/r14/run.py --mock [--part backup --part offer ...]

    backup.py     A  the drill passes on fakes; a missing document, a changed key, a live write, a
                     `(default)` target, empty stats each fail it; a stale backup alerts once
    selfwatch.py  B  3 failures -> one alert, recovery -> one info, clock gaps, the brief missed,
                     31 errors an hour, a spike, a revision; an outage rings at most once
    offer.py      C  120 labelled messages: the needed tool offered >= 98 %, <= 30 tools; the
                     window counts blocks; the ledger sums
    noai.py       D  every D12 row routes with zero provider calls; generative asks keep NO_AI_LINE
    needles.py    I1 a planted plaintext, nonce, key, exception text or prompt word reaches no
                     document, log line, audit detail or alert
    contract.py   I0 (BUILT) the parts' contract: every part builds through the real wiring and
                     owns only its tools, jobs and services; a stray part is refused. Its control
                     takes the contract check away: the refusals then fail

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

PARTS = ("backup", "selfwatch", "offer", "noai", "needles", "contract")


def load(part: str) -> ModuleType | None:
    """The part's module, by path under a unique name (no clash with any other `backup`)."""
    path = HERE / f"{part}.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(f"r14_{part}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _missing(part: str) -> dict[str, Any]:
    return {"id": f"{part}:missing", "passed": False, "failures": [f"evals/r14/{part}.py"]}


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
    return finish(HERE, "r14", results, combined(controls, parts))


if __name__ == "__main__":
    sys.exit(main())
