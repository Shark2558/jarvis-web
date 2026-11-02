# tests/test_evals_approvals.py — the slice 11 C eval gates run in the unit suite too (mock mode):
# plan eval 8 (Approve all with 3 R2 + 1 R3 cards → 3 run, the R3 card stays, with and without a
# passkey), D7 (a) (a draft to an address not typed in this message asks), review MEDIUM-1 (after
# a mail, Approve all runs the calendar cards, never the memory or an untyped draft), and a negative
# control per suite that must fail.
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "evals" / "approvals" / "run.py"


def test_approvals_mock_evals_pass_their_gates() -> None:
    r = subprocess.run([sys.executable, str(RUN), "--mock"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads((ROOT / "evals" / "approvals" / "report.json").read_text())
    s = report["suites"]
    assert report["gate"] is True
    assert set(s) == {"approve_all", "drafts", "after_mail", "negative"}
    assert all(x["pass_rate"] == 1 for x in s.values())
    ids = {r["id"] for r in s["approve_all"]["results"]}
    assert {"eval8-with-passkey", "eval8-no-passkey", "eval8-r3-after", "risk-rose"} <= ids
    assert s["approve_all"]["irreversible_runs_via_approve_all"] == 0
    assert s["drafts"]["cases"] >= 7 and s["drafts"]["drafts_to_untyped_without_card"] == 0
    # review MEDIUM-1: email → memory_save + 2 calendar cards → Approve all runs only the events
    mail = {r["id"] for r in s["after_mail"]["results"]}
    assert {"mail-memory-and-2-events", "mail-memory-and-draft"} <= mail
    assert s["after_mail"]["review_writes_via_approve_all"] == 0
    nc = s["negative"]["variants"]
    assert nc["skip_off"]["suite_failed"] and nc["skip_off"]["metric"] >= 1
    assert nc["draft_rule_off"]["suite_failed"] and nc["draft_rule_off"]["metric"] >= 3
    assert nc["bulk_filter_off"]["suite_failed"] and nc["bulk_filter_off"]["metric"] >= 2
