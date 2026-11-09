# evals/voice/run.py
"""Slice 9 eval harness — voice.

Usage:
    python evals/voice/run.py              # mock (CI): scripted engines, in-process storage
    python evals/voice/run.py --mock       # same (run_all_mock passes it)
    python evals/voice/run.py --suite billing
    python evals/voice/run.py --real       # wit + spoken replies on the real Claude models with a
                                           # Haiku judge (needs JARVIS_ANTHROPIC_API_KEY; without
                                           # it: "skipped", exit 0)

Suites (mock; all gates hard, 100 %):
  speakable  ≥ 40 cases (cases_speakable.jsonl): markdown, code, tables, URLs, emoji, control and
             bidi characters, the 600-character cap, nothing-to-say.
  persona    every hard limit in each wit variant; variants distinct and stable; the owner's
             variant reaches the model (chat + stream); the spoken-reply rule only on `voice`;
             training brains get wit and the rule but still no tools.
  billing    16 cases: ₹0 within the free allowance (also at the limit), only the excess priced
             when crossing it, US$30 / US$160 per 1 M characters and US$0.024/min at the day's
             rate, 0 priced calls past the limit, unreadable limit → no priced call. Negative
             control: the gate switched off (Billing.ensure_units_allowed a no-op) MUST fail.
  errors     Google's 403 / 401 / 429 / 400 / 5xx / timeouts / garbage → the API's status, code
             and reason; api_disabled remembered (no second request), transient errors not;
             vendor text never reaches the owner; no credentials / cloud off → no request at all.
  wav        transcribe input validation through the API: non-WAV, wrong content type, stereo,
             44.1 / 48 kHz, 8-bit, float, too short, too long, oversize (413 before reading),
             truncated → 0 STT calls.
  hints      R5 (D16): the owner's words to recognise reach the speech engine after the base hints,
             de-duplicated and bounded (50 words of 1-40 characters); refused lists give a 422 that
             never echoes them and nothing reaches the engine. Negative control: with the list
             validation off the suite MUST fail.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from hints import suite_hints  # noqa: E402
from suites import (  # noqa: E402
    suite_billing,
    suite_errors,
    suite_persona,
    suite_speakable,
    suite_wav,
)

from jarvis.logging import configure_logging  # noqa: E402


async def _speakable() -> dict[str, Any]:
    return suite_speakable()


SUITES: dict[str, Callable[[], Awaitable[dict[str, Any]]]] = {
    "speakable": _speakable,
    "persona": suite_persona,
    "billing": suite_billing,
    "errors": suite_errors,
    "wav": suite_wav,
    "hints": suite_hints,
}


def _summary(name: str, s: dict[str, Any]) -> str:
    base = f"{s['pass_rate']:.0%} of {s['cases']} cases"
    if name == "hints":
        nc = s["negative_control"]
        verdict = "fails as it must" if nc["suite_failed"] else "DID NOT FAIL: suite is blind"
        return f"{base}; negative control {verdict} ({nc['failed_cases']} cases)"
    if name == "billing":
        nc = s["negative_control"]
        verdict = "fails as it must" if nc["suite_failed"] else "DID NOT FAIL: suite is blind"
        return (
            f"{base}; priced calls past the limit {s['priced_calls_past_limit']} (gate 0); "
            f"negative control {verdict} ({nc['failed_cases']} cases, "
            f"{nc['priced_calls_past_limit']} priced calls past the limit)"
        )
    return base


async def run_mock(only: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, fn in SUITES.items():
        if only not in ("all", name):
            continue
        s = await fn()
        out[name] = s
        print(f"{name:10} {'PASS' if s['gate'] else 'FAIL'}  {_summary(name, s)}")
        for r in s["results"]:
            if not r["passed"]:
                print(f"    {r['id']} {r['why']}: {'; '.join(r['failures'])}")
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="default; kept for run_all_mock")
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--suite", choices=("all", *SUITES), default="all")
    args = ap.parse_args()
    configure_logging("CRITICAL", False)
    if args.real:
        if not os.environ.get("JARVIS_ANTHROPIC_API_KEY"):
            print("--real skipped: it needs JARVIS_ANTHROPIC_API_KEY (the Claude models).")
            return 0
        from real import real_suite

        real = await real_suite()
        report = {"mode": "real", "suites": {"real": real}, "gate": real["gate"]}
    else:
        suites = await run_mock(args.suite)
        report = {"mode": "mock", "suites": suites, "gate": all(s["gate"] for s in suites.values())}
    (HERE / "report.json").write_text(json.dumps(report, indent=2, default=str))
    print("\nGATE:", "PASS" if report["gate"] else "FAIL")
    return 0 if report["gate"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
