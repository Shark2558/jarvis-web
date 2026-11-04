# tests/test_evals_telegram.py -- the R1 Telegram eval gates run in the unit suite too
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "evals" / "telegram" / "run.py"


def test_telegram_evals_pass_their_gates() -> None:
    r = subprocess.run([sys.executable, str(RUN), "--mock"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads((ROOT / "evals" / "telegram" / "report.json").read_text())
    suite = report["suites"]["telegram"]
    assert suite["cases"] == 24 and suite["pass_rate"] == 1
    controls = report["negative_controls"]
    assert set(controls) == {"secret", "binding", "r3", "channel"}
    for name, c in controls.items():
        assert c["blind"] == [] and c["failed"] == len(c["cases"]), name  # each control bites


def test_the_case_file_and_the_runner_agree() -> None:
    declared = [
        json.loads(ln)["id"]
        for ln in (ROOT / "evals" / "telegram" / "cases.jsonl").read_text().splitlines()
        if ln
    ]
    assert len(declared) == 24 and len(set(declared)) == 24
