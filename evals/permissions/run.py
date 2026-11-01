# evals/permissions/run.py
"""Slice 10 D eval harness — owner permission rules and passkeys for irreversible approvals.

Usage:
    python evals/permissions/run.py            # mock (CI): the real app, mock brain, in-process
    python evals/permissions/run.py --mock     # same (run_all_mock passes it)
    python evals/permissions/run.py --suite passkey

No network and no model: passkeys are made by a software authenticator (authenticator.py) and
verified by py_webauthn exactly as a browser's would be.

Suites (all gates hard, 100 %):
  matrix    every group × Allow / Ask first / Never × every risk its tools can have, through the
            real gateway; Allow on an irreversible group refused (validation, stored value, Policy);
            an owner's Allow never relaxes a spoken turn or a tainted round. 0 R3 runs.
  deny      Never through the API: no card, the tool never runs, the model is told in plain words,
            the audit names the rule; a card made before Never doesn't run; other groups unaffected.
  passkey   register → approve with the real ceremony (exactly one send); refused with 0 sends:
            no assertion, the CLI bearer, replay, expired (2 min), another card, another purpose,
            another origin, another RP ID, no user verification, a counter going backwards; an R2
            card needs none; lowering protection (switch off, remove, add another) needs proof.
  negative  the passkey suite with the approval guard switched off MUST fail (else it is blind).
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
    suite_deny,
    suite_matrix,
    suite_negative_control,
    suite_passkey,
)

from jarvis.logging import configure_logging  # noqa: E402

SUITES: dict[str, Callable[[], Awaitable[dict[str, Any]]]] = {
    "matrix": suite_matrix,
    "deny": suite_deny,
    "passkey": suite_passkey,
    "negative": suite_negative_control,
}


def _summary(name: str, s: dict[str, Any]) -> str:
    base = f"{s['pass_rate']:.0%} of {s['cases']} cases"
    if name == "passkey":
        return (
            f"{base}; irreversible runs without a passkey {s['unconfirmed_r3_executions']} (gate 0)"
        )
    if name == "negative":
        verdict = "fails as it must" if s["suite_failed"] else "DID NOT FAIL: suite is blind"
        return (
            f"guard off → passkey suite {verdict} ({s['failed_cases']} cases, "
            f"{s['unconfirmed_r3_executions']} irreversible runs without a passkey)"
        )
    if name == "matrix":
        return f"{base}; R3 runs without approval {s['unconfirmed_r3']} (gate 0)"
    return base


async def run(only: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, fn in SUITES.items():
        if only not in ("all", name):
            continue
        s = await fn()
        out[name] = s
        print(f"{name:9} {'PASS' if s['gate'] else 'FAIL'}  {_summary(name, s)}")
        for r in s["results"]:
            if not r["passed"] and name != "negative":
                print(f"    {r['id']} {r['why']}: {'; '.join(r['failures'])}")
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="default; kept for run_all_mock")
    ap.add_argument("--suite", choices=("all", *SUITES), default="all")
    args = ap.parse_args()
    configure_logging("CRITICAL", False)
    suites = await run(args.suite)
    report = {"mode": "mock", "suites": suites, "gate": all(s["gate"] for s in suites.values())}
    (HERE / "report.json").write_text(json.dumps(report, indent=2, default=str))
    print("\nGATE:", "PASS" if report["gate"] else "FAIL")
    return 0 if report["gate"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
