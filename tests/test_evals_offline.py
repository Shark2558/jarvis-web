# tests/test_evals_offline.py -- the R1 C offline-mode eval gates run in the unit suite too (mock
# mode): 29 cases over fallback / tools / url, each negative control must make its suite fail.
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "evals" / "offline" / "run.py"


def test_offline_mock_evals_pass_their_gates() -> None:
    r = subprocess.run([sys.executable, str(RUN), "--mock"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads((ROOT / "evals" / "offline" / "report.json").read_text())
    s = report["suites"]
    assert report["gate"] is True
    assert set(s) == {"fallback", "tools", "url", "negative"}
    assert all(x["pass_rate"] == 1 for x in s.values())
    assert s["fallback"]["cases"] + s["tools"]["cases"] + s["url"]["cases"] >= 18
    ids = {x["id"] for x in s["fallback"]["results"]}
    assert {
        "cloud-503",
        "cloud-529-overloaded",
        "cloud-429-never-falls-back",
        "cloud-401-never-falls-back",
        "cloud-400-never-falls-back",
        "monthly-limit-never-falls-back",
        "breaker-skips-cloud-then-retries",
        "stream-mid-way-never-switches",
    } <= ids
    uids = {x["id"] for x in s["url"]["results"]}
    assert {
        "refuse-plain-http",
        "refuse-ip-literal",
        "refuse-metadata-address",
        "refuse-redirect",
    } <= uids
    nc = s["negative"]["variants"]
    assert (
        nc["fallback_on_every_error"]["suite_failed"]
        and nc["fallback_on_every_error"]["metric"] >= 3
    )
    assert nc["writes_ask_off"]["suite_failed"] and nc["writes_ask_off"]["metric"] >= 1
    assert nc["url_rule_off"]["suite_failed"] and nc["url_rule_off"]["metric"] >= 5
