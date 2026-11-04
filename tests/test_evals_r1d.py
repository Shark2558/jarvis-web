# tests/test_evals_r1d.py -- the R1 builder D mock eval suites run in the unit suite too.
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MIN_CASES = {"packages": 5, "groceries": 14, "family": 12, "mail_aloud": 14}


@pytest.mark.parametrize("suite", sorted(MIN_CASES))
def test_suite_passes_and_its_negative_control_fails_it(suite: str) -> None:
    run = ROOT / "evals" / suite / "run.py"
    r = subprocess.run([sys.executable, str(run), "--mock"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads((ROOT / "evals" / suite / "report.json").read_text())
    assert report["cases"] >= MIN_CASES[suite] and report["pass_rate"] == 1.0
    assert report["negative_control"]["suite_failed"] is True
