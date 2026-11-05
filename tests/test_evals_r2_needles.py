# tests/test_evals_r2_needles.py -- R2 I1: the cross-cutting needle scan runs in the unit suite too
# (mock): 20 conversations + 5 scans pass, and ignoring `Tool.activity_words` makes it fail.
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "evals" / "r2_needles" / "run.py"


def test_r2_needles_pass_and_the_activity_words_control_fails_the_suite() -> None:
    r = subprocess.run([sys.executable, str(RUN), "--mock"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    report = json.loads((ROOT / "evals" / "r2_needles" / "report.json").read_text())
    ids = [x["id"] for x in report["results"]]
    assert report["pass_rate"] == 1.0 and len(ids) == 25
    assert len([i for i in ids if not i.startswith("scan_")]) == 20
    assert {"typed_where_positive_control", "training_brain_same_session"} <= set(ids)
    control = report["negative_control"]
    assert control["suite_failed"] is True and "scan_activity_rows" in control["failed_cases"]
