# evals/calls_language/run.py
"""R18 B eval harness — the calls language check (docs/plans/r18-calls.md 5.3, 11).

Usage:
    python evals/calls_language/run.py           # mock (CI): scripted options, no network
    python evals/calls_language/run.py --mock    # same (run_all_mock passes it)
    python evals/calls_language/run.py --suite check

Suites (mock; all gates hard, 100 %, each with a negative control that MUST fail it): scoring,
phoneline, selection, free_first (the app's own choice, R18 review), check (see suites.py). The
real check (FLEURS clips, real speech options) runs from the Calls panel, never in CI: no network
and no paid speech here.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from suites import (  # noqa: E402
    suite_check,
    suite_free_first,
    suite_phoneline,
    suite_scoring,
    suite_selection,
)

from jarvis.logging import configure_logging  # noqa: E402

SUITES: dict[str, Callable[[], Awaitable[dict[str, Any]]]] = {
    "scoring": suite_scoring,
    "phoneline": suite_phoneline,
    "selection": suite_selection,
    "free_first": suite_free_first,
    "check": suite_check,
}


def _summary(s: dict[str, Any]) -> str:
    nc = s["negative_control"]
    verdict = "fails as it must" if nc["suite_failed"] else "DID NOT FAIL: suite is blind"
    base = f"{s['pass_rate']:.0%} of {s['cases']} cases"
    return f"{base}; negative control {verdict} ({nc['failed_cases']} cases)"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="default; kept for run_all_mock")
    ap.add_argument("--suite", choices=("all", *SUITES), default="all")
    args = ap.parse_args()
    configure_logging("CRITICAL", False)
    out: dict[str, Any] = {}
    for name, fn in SUITES.items():
        if args.suite not in ("all", name):
            continue
        s = await fn()
        out[name] = s
        print(f"{name:10} {'PASS' if s['gate'] else 'FAIL'}  {_summary(s)}")
        for r in s["results"]:
            if not r["passed"]:
                print(f"    {r['id']} {r['why']}: {'; '.join(r['failures'])}")
    report = {"mode": "mock", "suites": out, "gate": all(s["gate"] for s in out.values())}
    (HERE / "report.json").write_text(json.dumps(report, indent=2, default=str))
    print("\nGATE:", "PASS" if report["gate"] else "FAIL")
    return 0 if report["gate"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
