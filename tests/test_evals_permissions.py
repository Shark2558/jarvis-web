# tests/test_evals_permissions.py — the slice 10 D eval gates run in the unit suite too (mock mode):
# the policy matrix, the deny path, passkey ceremonies, and a negative control that must fail.
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "evals" / "permissions" / "run.py"


def test_permissions_mock_evals_pass_their_gates() -> None:
    r = subprocess.run([sys.executable, str(RUN), "--mock"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads((ROOT / "evals" / "permissions" / "report.json").read_text())
    s = report["suites"]
    assert report["gate"] is True and set(s) == {"matrix", "deny", "passkey", "negative"}
    assert all(x["pass_rate"] == 1 for x in s.values())
    assert s["matrix"]["cases"] >= 40 and s["matrix"]["unconfirmed_r3"] == 0
    assert s["passkey"]["cases"] >= 12 and s["passkey"]["unconfirmed_r3_executions"] == 0
    ids = {r["id"] for r in s["passkey"]["results"]}
    assert {"replay", "expired", "wrong-approval", "wrong-origin", "no-assertion"} <= ids
    # without the guard the suite fails: it can see an irreversible action run unconfirmed
    nc = s["negative"]
    assert nc["suite_failed"] is True and nc["unconfirmed_r3_executions"] >= 5
