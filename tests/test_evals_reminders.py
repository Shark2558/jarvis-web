# tests/test_evals_reminders.py — the slice 11 B reminder eval gates (plan evals 5 and 6) run in
# the unit suite too (mock).
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "evals" / "reminders" / "run.py"


def test_reminder_mock_evals_pass_their_gates() -> None:
    r = subprocess.run([sys.executable, str(RUN), "--mock"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads((ROOT / "evals" / "reminders" / "report.json").read_text())
    s = report["suite"]
    assert report["gate"] is True and s["pass_rate"] == 1.0
    assert s["cases"] >= 10 and s["unapproved_writes"] == 0
    ids = {row["id"] for row in s["results"]}
    assert {"e5-remind-at-5pm", "e6-remind-before-3pm-meeting"} <= ids  # the plan's evals
    # with the reminder made to block time and lose its tag, the same checks fail
    assert s["negative_control"]["suite_failed"] is True


def test_the_suite_is_wired_into_run_all_mock() -> None:
    text = (ROOT / "evals" / "run_all_mock.py").read_text()
    assert (
        '("reminders (gated)", [sys.executable, str(HERE / "reminders" / "run.py"), "--mock"], '
        "True)" in text
    )
