# tests/test_evals_undo.py — the slice 11 A undo eval gates (plan evals 1, 2, 3, 4, 7 and 9) run in
# the unit suite too (mock).
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "evals" / "undo" / "run.py"


def test_undo_mock_evals_pass_their_gates() -> None:
    r = subprocess.run([sys.executable, str(RUN), "--mock"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads((ROOT / "evals" / "undo" / "report.json").read_text())
    s = report["suite"]
    assert report["gate"] is True and s["pass_rate"] == 1.0
    assert s["cases"] >= 14 and s["unapproved_deletes"] == 0
    assert s["evals"] == [1, 2, 3, 4, 7, 9]  # the plan's evals this workstream owns
    # each negative control (tainted-writes rule off, 10-delete cap off, a bin that "keeps"
    # without storing, the D8 trusted flag ignored) makes its cases fail: the gates test
    # something real
    controls = s["negative_controls"]
    assert set(controls) == {"tainted", "cap", "leaky", "trust"}
    assert all(v["cases"] and v["suite_failed"] for v in controls.values())
    # plan D8 (provenance-based trust): look up then delete, and "undo", run without a card;
    # with the flag ignored they are cards again
    assert {"u01-e1-delete-dentist", "u01b-e1-lookup-then-delete"} <= set(s["d8"])
    assert set(controls["trust"]["failed"]) == set(controls["trust"]["cases"])


def test_the_suite_is_wired_into_run_all_mock() -> None:
    text = (ROOT / "evals" / "run_all_mock.py").read_text()
    assert (
        '("undo (gated)", [sys.executable, str(HERE / "undo" / "run.py"), "--mock"], True)' in text
    )
