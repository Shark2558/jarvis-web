# tests/test_evals_r2b.py -- the R2 builder B mock eval suites (DigiLocker inbox, Things) run in the
# unit suite too: every case passes, and each negative control makes its suite fail.
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MIN_CASES = {"digilocker": 15, "belongings": 25}


@pytest.mark.parametrize("suite", sorted(MIN_CASES))
def test_suite_passes_and_its_negative_controls_fail_it(suite: str) -> None:
    run = ROOT / "evals" / suite / "run.py"
    r = subprocess.run([sys.executable, str(run), "--mock"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads((ROOT / "evals" / suite / "report.json").read_text())
    assert report["cases"] >= MIN_CASES[suite] and report["pass_rate"] == 1.0
    control = report["negative_control"]
    assert control["suite_failed"] is True
    assert all(control["failed_cases"].values())  # each control broke something on its own
