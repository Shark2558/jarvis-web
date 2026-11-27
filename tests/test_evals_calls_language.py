# tests/test_evals_calls_language.py — R18 B: the language check's mock eval gates run in the unit
# suite too: every suite at 100 %, and every negative control fails it as it must.
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "evals" / "calls_language" / "run.py"


def test_calls_language_mock_evals_pass_their_gates() -> None:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    r = subprocess.run(
        [sys.executable, str(RUN), "--mock"], capture_output=True, text=True, env=env, timeout=240
    )
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads((ROOT / "evals" / "calls_language" / "report.json").read_text())
    suites = report["suites"]
    assert report["gate"] is True and report["mode"] == "mock"
    assert set(suites) == {"scoring", "phoneline", "selection", "check"}
    for s in suites.values():
        assert s["pass_rate"] == 1
        assert s["negative_control"]["suite_failed"] is True
