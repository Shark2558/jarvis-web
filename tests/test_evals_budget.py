# tests/test_evals_budget.py — the slice 7b eval gates run in the unit suite too (mock mode)
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "evals" / "budget" / "run.py"


def test_budget_mock_evals_pass_their_gates() -> None:
    r = subprocess.run([sys.executable, str(RUN), "--mock"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads((ROOT / "evals" / "budget" / "report.json").read_text())
    s = report["suites"]["budget"]
    assert report["gate"] is True and report["mode"] == "mock"
    assert s["pass_rate"] == 1 and s["cases"] >= 12
    assert s["paid_calls_past_limit"] == 0 and s["dollars_shown"] == 0
    kinds = {x["kind"] for x in s["results"]}
    assert {"chat", "stream", "tools", "narration", "brief", "budget"} <= kinds
    # without the gate the suite fails: it can see a missing limit check
    nc = s["negative_control"]
    assert nc["suite_failed"] is True and nc["failed_cases"] >= 8
