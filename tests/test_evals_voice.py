# tests/test_evals_voice.py — the slice 9 eval gates run in the unit suite too (mock mode), and the
# --real mode skips cleanly without a key.
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "evals" / "voice" / "run.py"


def test_voice_mock_evals_pass_their_gates() -> None:
    r = subprocess.run([sys.executable, str(RUN), "--mock"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads((ROOT / "evals" / "voice" / "report.json").read_text())
    s = report["suites"]
    assert report["gate"] is True and report["mode"] == "mock"
    assert set(s) == {"speakable", "persona", "billing", "errors", "wav"}
    assert all(x["pass_rate"] == 1 for x in s.values())
    assert s["speakable"]["cases"] >= 40
    assert s["persona"]["cases"] >= 20
    bill = s["billing"]
    assert bill["cases"] >= 12 and bill["priced_calls_past_limit"] == 0
    # without the gate the suite fails: it can see a priced call past the limit
    nc = bill["negative_control"]
    assert nc["suite_failed"] is True and nc["priced_calls_past_limit"] > 0
    assert nc["failed_cases"] >= 5
    reasons = {r["id"] for r in s["errors"]["results"]}
    assert len(reasons) >= 15
    assert s["wav"]["cases"] >= 12


def test_voice_real_mode_skips_cleanly_without_a_key() -> None:
    env = {k: v for k, v in os.environ.items() if k != "JARVIS_ANTHROPIC_API_KEY"}
    r = subprocess.run(
        [sys.executable, str(RUN), "--real"], capture_output=True, text=True, env=env, cwd=ROOT
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "skipped" in r.stdout
