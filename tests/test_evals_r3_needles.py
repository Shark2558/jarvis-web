# tests/test_evals_r3_needles.py -- the R3 I1 needle scan runs in the unit suite too (mock mode)
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "evals" / "r3_needles" / "run.py"


def test_r3_needles_pass_and_a_debug_log_of_webhook_bodies_fails_the_suite() -> None:
    r = subprocess.run([sys.executable, str(RUN), "--mock"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    report = json.loads((RUN.parent / "report.json").read_text())
    assert report["pass_rate"] == 1 and report["cases"] >= 11
    control = report["negative_control"]
    assert control["suite_failed"] is True
    assert "n07_snapshot_with_opt_in_only_as_a_photo" in control["failed_cases"][control["name"]]
