# evals/realrun/runner.py
"""Runs the chosen suites one after the other, each in its own process under the spend guard
(`run_real.py guard …`), with its technical output kept in a log file, and tells the owner in
plain English what passed, what it cost and what to do next. Stops at the safety stop."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from jarvis.billing import rupees
from realrun.estimate import Estimate, Suite
from realrun.guard import EXIT_CAP, EXIT_UNMETERED, Ledger
from realrun.summary import summarize

RUN_REAL = Path(__file__).resolve().parents[1] / "run_real.py"


def _report(path: Path, before: int | None) -> dict[str, Any] | None:
    """The suite's report, only if this run wrote it (an older one is not this run's result)."""
    try:
        if path.stat().st_mtime_ns == before:
            return None
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _mtime(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def _duration(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f} seconds"
    return f"{seconds / 60:.0f} minutes"


def run_suites(
    *,
    suites: Sequence[Suite],
    estimate: Estimate,
    ledger: Ledger,
    logs: Path,
    env: Mapping[str, str],
    root: Path,
    say: Callable[[str], None],
) -> int:
    """0: every suite ran and passed · 1: something did not pass · 3: safety stop · 4: unpriced."""
    logs.mkdir(parents=True, exist_ok=True)
    passed: list[bool] = []
    stopped = 0
    for i, s in enumerate(suites, 1):
        say(f"\nRunning {i} of {len(suites)}: {s.title} ...")
        report_path = root / s.report
        before = _mtime(report_path)
        log_path = logs / f"{s.key}.log"
        cmd = [
            sys.executable,
            str(RUN_REAL),
            "guard",
            "--cap-usd",
            f"{estimate.cap_usd:.6f}",
            "--ledger",
            str(ledger.path),
            str(root / s.argv[0]),
            *s.argv[1:],
        ]
        t0 = time.monotonic()
        with log_path.open("w") as log:
            rc = subprocess.run(
                cmd, cwd=root, env=dict(env), stdout=log, stderr=subprocess.STDOUT, check=False
            ).returncode
        ok, lines = summarize(s.key, _report(report_path, before))
        passed.append(ok and rc == 0)
        for line in lines:
            say("  " + line)
        say(f"  (took {_duration(time.monotonic() - t0)}; full output: {log_path})")
        if rc in (EXIT_CAP, EXIT_UNMETERED):
            stopped = rc
            break
    try:
        spent = rupees(ledger.read() * estimate.inr_per_usd)
    except (OSError, ValueError):  # the suites stopped on this too (fail closed)
        spent, stopped = "unknown (the spending record could not be read)", stopped or EXIT_CAP
    say(
        f"\nSpent: about {spent} (estimate {rupees(estimate.total_inr)},"
        f" safety stop {rupees(estimate.cap_inr)})."
    )
    if stopped == EXIT_CAP:
        say(
            "The run reached its safety stop, so it stopped by itself. Nothing more was spent;"
            " the remaining tests did not run."
        )
    elif stopped == EXIT_UNMETERED:
        say("A test asked for a Claude model whose price is unknown, so it was not called.")
    all_ok = not stopped and len(passed) == len(suites) and all(passed)
    _next_steps(all_ok, say)
    return stopped or (0 if all_ok else 1)


def _next_steps(all_ok: bool, say: Callable[[str], None]) -> None:
    say("\nWhat to do next:")
    if all_ok:
        say('  1. Tell Claude: "real evals passed". Nothing else is needed.')
        return
    say("  1. Copy everything printed above, from the first 'Running' line down.")
    say("  2. Send it to Claude. The detailed reports are saved in the evals folders.")


__all__ = ["run_suites"]
