# tests/test_evals_trust.py — the slice 11 D8 trust eval gates run in the unit suite too (mock).
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "evals" / "trust" / "run.py"


def test_trust_mock_evals_pass_their_gates_and_both_controls_fail() -> None:
    r = subprocess.run([sys.executable, str(RUN), "--mock"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads((ROOT / "evals" / "trust" / "report.json").read_text())
    s = report["suite"]
    assert report["gate"] is True and s["pass_rate"] == 1.0 and s["unapproved_writes"] == 0
    assert s["d8"] == [1, 2, 3, 4, 5]  # every D8 eval the brief names has a case (+ outside)
    controls = s["negative_controls"]
    assert controls["flag"]["suite_failed"] and controls["flag"]["cases"]  # flag ignored
    assert controls["rule"]["suite_failed"] and controls["rule"]["cases"]  # rule skipped
    # nothing JARVIS writes from a mail marked as outside: the later delete runs uncarded
    assert controls["marker"]["suite_failed"]
    assert "t5-todo-from-a-mail-later-delete" in controls["marker"]["cases"]


def test_the_suite_is_wired_into_run_all_mock() -> None:
    text = (ROOT / "evals" / "run_all_mock.py").read_text()
    assert (
        '("trust (gated)", [sys.executable, str(HERE / "trust" / "run.py"), "--mock"], True)'
        in (text)
    )
