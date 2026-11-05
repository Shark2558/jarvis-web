# tests/test_evals_activity.py -- the R1 B Activity eval gates run in the unit suite too (mock mode)
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "evals" / "activity" / "run.py"


def test_activity_mock_evals_pass_their_gates_and_their_negative_controls_fail() -> None:
    r = subprocess.run([sys.executable, str(RUN), "--mock"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads((ROOT / "evals" / "activity" / "report.json").read_text())
    s = report["suites"]["activity"]
    assert report["gate"] is True and report["mode"] == "mock"
    assert s["pass_rate"] == 1 and s["cases"] >= 14
    # each negative control must make the suite fail: the suite is not blind
    nc = s["negative_controls"]
    assert nc["observer_off"] >= 8
    assert nc["every_undo_id_restorable"] >= 2


def test_a_single_case_can_be_run_on_its_own() -> None:
    r = subprocess.run(
        [sys.executable, str(RUN), "--mock", "--only", "a07"], capture_output=True, text=True
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "a07" in r.stdout and "a01" not in r.stdout
