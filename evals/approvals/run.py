# evals/approvals/run.py
"""Slice 11 workstream C eval harness — Approve all (plan eval 8), D7 (a) draft recipients, and
(review MEDIUM-1) Approve all after a mail: the events run, the memory and an untyped draft don't.

Usage:
    python evals/approvals/run.py            # mock (CI): the real app / Brain, mock model
    python evals/approvals/run.py --mock     # same (run_all_mock passes it)
    python evals/approvals/run.py --suite drafts

No network and no model. The Approve all suite reuses the slice 10 D permission rig
(evals/permissions/harness.py: Google sign-in mode, a software authenticator for passkeys).
Suites and gates (all hard, 100 %): see evals/approvals/suites.py.
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
sys.path.insert(1, str(HERE.parent / "permissions"))  # the slice 10 D rig (harness, authenticator)

from suites import (  # noqa: E402
    suite_after_mail,
    suite_approve_all,
    suite_drafts,
    suite_negative_control,
)

from jarvis.logging import configure_logging  # noqa: E402

SUITES: dict[str, Callable[[], Awaitable[dict[str, Any]]]] = {
    "approve_all": suite_approve_all,
    "drafts": suite_drafts,
    "after_mail": suite_after_mail,
    "negative": suite_negative_control,
}


def _summary(name: str, s: dict[str, Any]) -> str:
    base = f"{s['pass_rate']:.0%} of {s['cases']} cases"
    if name == "approve_all":
        return f"{base}; irreversible runs via Approve all {s['irreversible_runs_via_approve_all']}"
    if name == "drafts":
        n = s["drafts_to_untyped_without_card"]
        return f"{base}; drafts to untyped addresses without a card {n}"
    if name == "after_mail":
        n = s["review_writes_via_approve_all"]
        return f"{base}; memory writes / untyped drafts run by Approve all {n}"
    parts = [
        f"{v} → {'fails as it must' if d['suite_failed'] else 'DID NOT FAIL: suite is blind'}"
        f" (metric {d['metric']})"
        for v, d in s["variants"].items()
    ]
    return "; ".join(parts)


async def run(only: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, fn in SUITES.items():
        if only not in ("all", name):
            continue
        s = await fn()
        out[name] = s
        print(f"{name:11} {'PASS' if s['gate'] else 'FAIL'}  {_summary(name, s)}")
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
