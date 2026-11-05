# tests/test_evals_notify.py -- R3 D: the notify eval gate runs in the unit suite too (mock mode):
# every case passes and each of the five negative controls makes the suite fail.
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "evals" / "notify" / "run.py"


def test_notify_mock_evals_pass_their_gates() -> None:
    r = subprocess.run([sys.executable, str(RUN), "--mock"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    report = json.loads((ROOT / "evals" / "notify" / "report.json").read_text())
    ids = {x["id"] for x in report["results"]}
    assert report["pass_rate"] == 1.0 and report["cases"] >= 46
    assert {
        "push:rfc8291_appendix_a",
        "channels:zero_model_calls",
        "storm:fifty_detections_in_two_minutes",
    } <= ids
    controls = report["negative_control"]["controls"]
    assert set(controls) == {
        "quiet_hours_off",
        "vip_check_off",
        "storm_cap_off",
        "endpoint_allow_list_off",
        "urgent_bucket_merged",
    }
    assert all(controls.values())
