# tests/test_evals_home_link.py -- the R3 A home-link eval runs in the unit suite too (mock mode)
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "evals" / "home_link" / "run.py"
CONTROLS = (
    "signature_check_off",
    "time_window_off",
    "same_key_both_ways",
    "allow_list_off",
    "url_rule_off",
)


def test_home_link_eval_passes_and_every_negative_control_fails_the_suite() -> None:
    r = subprocess.run([sys.executable, str(RUN), "--mock"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    report = json.loads((RUN.parent / "report.json").read_text())
    assert report["pass_rate"] == 1 and report["cases"] >= 44
    failed = report["negative_control"]["failed_cases"]
    assert report["negative_control"]["suite_failed"] is True
    for name in CONTROLS:
        assert failed[name], f"{name} did not make any case fail"
