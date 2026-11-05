# tests/test_evals_home_alarm.py -- the R3 B mock eval (home alarm, history, parcels) runs in the
# suite too: every case passes, and each negative control makes the suite fail on its own.
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIN_CASES = 40


def test_suite_passes_and_its_negative_controls_fail_it() -> None:
    run = ROOT / "evals" / "home_alarm" / "run.py"
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    r = subprocess.run(
        [sys.executable, str(run), "--mock"], capture_output=True, text=True, env=env
    )
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads((ROOT / "evals" / "home_alarm" / "report.json").read_text())
    assert report["cases"] >= MIN_CASES and report["pass_rate"] == 1.0
    control = report["negative_control"]
    assert control["suite_failed"] is True
    assert set(control["failed_cases"]) == {
        "disarmed_filter_off",
        "recognition_may_suppress",
        "history_passes_bridge_strings",
        "disarm_tool_disarms",
    }
    assert all(control["failed_cases"].values())  # each control broke something on its own
