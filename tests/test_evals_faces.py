# tests/test_evals_faces.py -- the R3 C mock eval suite (Faces and consent) in the unit suite:
# every case passes, and each negative control makes the suite fail on its own.
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIN_CASES = 32


def test_suite_passes_and_its_negative_controls_fail_it() -> None:
    run = ROOT / "evals" / "faces" / "run.py"
    r = subprocess.run([sys.executable, str(run), "--mock"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads((ROOT / "evals" / "faces" / "report.json").read_text())
    assert report["cases"] >= MIN_CASES and report["pass_rate"] == 1.0
    control = report["negative_control"]
    assert control["suite_failed"] is True
    assert set(control["failed_cases"]) == {
        "registry_check_off",
        "bridge_consent_off",
        "children_rule_off",
    }
    assert all(control["failed_cases"].values())  # each control broke something on its own
