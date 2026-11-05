# tests/test_evals_vault.py -- the R2 A vault eval gates (mock) run in the unit suite too.
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "evals" / "vault" / "run.py"


def test_vault_mock_evals_pass_their_gates() -> None:
    r = subprocess.run([sys.executable, str(RUN), "--mock"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    suite = json.loads((ROOT / "evals" / "vault" / "report.json").read_text())["suite"]
    assert suite["cases"] >= 80 and suite["pass_rate"] == 1.0 and suite["failed"] == {}
    assert set(suite["groups"]) == {
        "leak",
        "roundtrip",
        "tamper",
        "purge",
        "ticket",
        "extract",
        "remind",
        "tools",
        "limits",
    }


def test_each_negative_control_makes_its_group_fail() -> None:
    suite = json.loads((ROOT / "evals" / "vault" / "report.json").read_text())["suite"]
    controls = suite["negative_controls"]
    assert set(controls) == {"plain_index", "aad_off", "expiry_off", "unconfirmed_alerts"}
    assert all(c["cases"] and c["suite_failed"] and c["failed"] for c in controls.values())


def test_a_single_group_can_be_run_alone() -> None:
    r = subprocess.run(
        [sys.executable, str(RUN), "--mock", "--only", "extract"], capture_output=True, text=True
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "cases" in r.stdout
