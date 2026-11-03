# tests/test_evals_media.py — the slice 12 Maps and YouTube eval gates run in the unit suite too
# (mock mode), with their negative control (ledger off → the stop and fail-closed cases fail).
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(("suite", "cases"), [("maps", 18), ("youtube", 10)])
def test_media_mock_evals_pass_and_the_negative_control_fails(suite: str, cases: int) -> None:
    run = ROOT / "evals" / suite / "run.py"
    r = subprocess.run([sys.executable, str(run), "--mock"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads((ROOT / "evals" / suite / "report.json").read_text())
    assert report["gate"] and len(report["results"]) == cases
    assert all(v == 0 for v in report["hard"].values()), report["hard"]
    assert report["negative_controls"]["ledger_off_fails"] is True
    # final review: the named cap / fail-closed cases each failed because Google was reached
    neg = report["negative_controls"]["ledger_off"]
    assert neg["missing_cases"] == [] and neg["reached_google"] == neg["must_reach_google"]
    assert (
        neg["must_reach_google"]
        == {"maps": ["m11", "m12", "m17"], "youtube": ["y03", "y09"]}[suite]
    )


@pytest.mark.parametrize("suite", ["maps", "youtube"])
def test_media_evals_refuse_a_real_run(suite: str) -> None:
    run = ROOT / "evals" / suite / "run.py"
    r = subprocess.run([sys.executable, str(run)], capture_output=True, text=True)
    assert r.returncode == 2 and "--mock" in r.stdout


def test_run_all_mock_gates_both_suites() -> None:
    text = (ROOT / "evals" / "run_all_mock.py").read_text()
    assert '("maps (gated)"' in text and '("youtube (gated)"' in text
