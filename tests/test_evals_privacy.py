# tests/test_evals_privacy.py - the R2 D14 privacy eval gates run in the unit suite too (mock).
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "evals" / "privacy" / "run.py"


def test_privacy_mock_evals_pass_their_gates_and_each_control_fails_the_suite() -> None:
    r = subprocess.run([sys.executable, str(RUN), "--mock"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    report = json.loads((ROOT / "evals" / "privacy" / "report.json").read_text())
    assert report["cases"] >= 30 and report["pass_rate"] == 1.0
    control = report["negative_control"]
    assert set(control["failed_cases"]) == {
        "binding_off",
        "owner_filter_off",
        "rev_check_off",
        "export_gate_off",
        "verify_off",
    }
    assert all(control["failed_cases"].values()) and control["suite_failed"] is True
    ids = {x["id"] for x in report["results"]}
    assert {"count-faces-placeholder-is-listed", "delete-this-months-spend-is-kept"} <= ids
