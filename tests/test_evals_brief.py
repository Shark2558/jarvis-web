# tests/test_evals_brief.py — the slice 7 eval gates run in the unit suite too (mock mode)
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "evals" / "brief" / "run.py"


def test_brief_mock_evals_pass_their_gates() -> None:
    r = subprocess.run([sys.executable, str(RUN), "--mock"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads((ROOT / "evals" / "brief" / "report.json").read_text())
    s = report["suites"]
    assert report["gate"] is True and report["mode"] == "mock"
    assert s["schedule"]["pass_rate"] == 1 and len(s["schedule"]["results"]) >= 15
    assert s["compose"]["pass_rate"] == 1 and len(s["compose"]["results"]) >= 12
    inj = s["injection"]
    assert inj["cases"] >= 15 and inj["gate"] is True
    for gate in (
        "links",
        "fence_markers",
        "control_chars",
        "tool_specs_passed",
        "training_brain_calls",
        "deterministic_changed",
        "unfenced_input",
        "text_links",  # no link anywhere in the plain-text brief (security review F1)
    ):
        assert inj[gate] == 0, gate
    assert s["compose"]["pass_rate"] == 1 and len(s["compose"]["results"]) >= 17
    assert inj["cases"] >= 34  # incl. the p_links.py cases i21-i34 (TLD-agnostic detector)
    # the scripted model really echoed the links: the sanitiser is what removed them …
    assert inj["raw_outputs_with_links"] >= 15
    # … and without it the suite fails (it is not blind)
    assert inj["negative_control"]["suite_failed"] is True
    assert inj["negative_control"]["failed_cases"] >= 15
