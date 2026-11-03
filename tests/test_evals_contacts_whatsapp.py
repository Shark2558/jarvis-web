# tests/test_evals_contacts_whatsapp.py — the slice 12 C eval gates run in the unit suite (mock).
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "evals" / "contacts_whatsapp" / "run.py"


def test_contacts_whatsapp_mock_evals_pass_and_the_control_fails() -> None:
    r = subprocess.run([sys.executable, str(RUN), "--mock"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads((RUN.parent / "report.json").read_text())
    s = report["suite"]
    assert report["gate"] is True and s["cases"] == 17 and s["pass_rate"] == 1.0
    ids = {r["id"] for r in s["results"]}
    assert {"r01-ask-first-contacts-name", "r02-tainted-round-draft-asks"} <= ids  # review S1, S3
    assert s["sends"] == 0 and s["unwarned"] == 0  # JARVIS sends nothing; outside numbers warn
    neg = report["negative_control"]
    assert neg["suite_failed"] and "w05-number-from-email" in neg["failed"]


def test_the_suite_is_wired_into_run_all_mock() -> None:
    text = (ROOT / "evals" / "run_all_mock.py").read_text()
    assert '[sys.executable, str(HERE / "contacts_whatsapp" / "run.py"), "--mock"]' in text
