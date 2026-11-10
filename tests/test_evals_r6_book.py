# tests/test_evals_r6_book.py -- builder C's R6 eval parts (access, guest, wipe, lock) run in the
# unit suite too (mock mode), each with a negative control that must make its part fail:
# guest = post-guard off / gateway specs given / pre-guard off / canary off (EACH alone fails it);
# access = the fresh sign-in check skipped; wipe = the delete skipped; lock = /auth/me allow-listed.
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "evals" / "r6_book" / "run.py"
PARTS = ("access", "guest", "wipe", "lock")
CONTROLS = ("post_guard_off", "gateway_specs_given", "pre_guard_off", "canary_off")
ACCESS_B_ROWS = {"access:guest-sections", "access:guest-older-sections", "access:guest-ticket"}


def test_builder_c_parts_pass_and_each_control_fails_its_part() -> None:
    args = [sys.executable, str(RUN), "--mock"] + [x for p in PARTS for x in ("--part", p)]
    r = subprocess.run(args, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-4000:]
    report = json.loads((ROOT / "evals" / "r6_book" / "report.json").read_text())
    ids = {x["id"] for x in report["results"]}
    assert report["passed"] == report["cases"] >= 120
    for part in PARTS:
        assert any(i.startswith(f"{part}:") for i in ids), part
    assert sum(i.startswith("guest:data-") for i in ids) >= 40
    assert sum(i.startswith("guest:feature-") for i in ids) == 12
    assert {
        "guest:canary-dump",
        "guest:canary-reworded",
        "guest:tool-attempt",
        "guest:echo-address",
        "guest:question-21-limit",
    } <= ids
    assert {"wipe:no-needle:logs", "wipe:audit-open-and-close-only"} <= ids
    assert "wipe:no-sealed-turns-left" in ids
    assert {
        "lock:new-sign-in:me",
        "lock:presenting:reset",
        "lock:fresh-guest-sign-in-lifts-nothing",
        "lock:no-passkey-no-sign-in-lift",
        "lock:resume-proof-lifts",
    } <= ids
    b_rows = [x for x in report["results"] if x["id"] in ACCESS_B_ROWS]
    assert len(b_rows) == 3 and not any(x.get("rerun_at_integration") for x in b_rows)  # I1: real
    nc = report["negative_control"]
    assert nc["suite_failed"] is True and nc["parts_not_built"] == []
    failed = nc["failed_cases"]
    guest = failed["guest"]
    assert all(guest[c] for c in CONTROLS)  # each control on its own fails the part
    assert {"guest:echo-address", "guest:canary-dump", "guest:canary-reworded"} <= set(
        guest["post_guard_off"]
    )
    assert {"guest:tools-always-none", "guest:feature-01"} <= set(guest["gateway_specs_given"])
    assert {"guest:action-send", "guest:data-01"} <= set(guest["pre_guard_off"])
    assert guest["canary_off"] == ["guest:canary-reworded"]  # only the canary catches it
    assert failed["access"] == ["access:stale-sign-in-reauth"]
    assert "wipe:session-document-absent" in failed["wipe"]
    assert "lock:presenting:me" in failed["lock"]
