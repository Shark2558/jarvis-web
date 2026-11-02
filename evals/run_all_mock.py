# evals/run_all_mock.py
"""Run every eval suite against the mock provider (CI plumbing + safety gates).

    python evals/run_all_mock.py

Equivalent to `make eval-mock` once the Makefile points here: phase0 (core loop plumbing),
slice6 (calendar correctness over a fixture + the injection suite, whose gates are hard) and the
slice 7 morning brief (due-logic, composed facts, AI-line injection containment + its negative
control) and slice 7b's monthly limit (rupees only; no paid call at or over the limit, on every
path; + its negative control) and slice 8's long-term memory (recall, poisoning, training-brain
gate, sensitive data, contradictions, round trip, budget; + negative controls) and slice 9's
voice (speakable text, persona per wit level, voice billing past the free allowance + its
negative control, provider error mapping, transcribe input validation) and slice 10 B's web search
(citations, injection pages, the private-query guard; + two negative controls) and slice 10 C's
to-do list (Google Tasks tools: correctness, the optional scope, injection in task notes → 0
deletes without approval; + its negative control) and slice 10 D's permissions (policy matrix,
deny path, passkey ceremonies with a software authenticator; + its negative control) and slice
10 E's attached documents (extraction limits, recall via doc_search from a 100-page PDF,
injection inside a document + its negative control, training-brain privacy) and slice 11 B's
reminders (plan evals 5 and 6: tagged pop-up events, alerts before a meeting; + its negative
control) and slice 11 A's undo-able deletes (plan evals 1, 2, 3, 4, 7, 9: own items deleted with
Undo, shared ones R3, a mail can't delete, the 10-delete cap, restore, fail-closed snapshots; +
negative controls), slice 11 C's approvals (plan eval 8, Approve all: 3 R2 run, R3 stays;
drafts to un-typed addresses ask; + negative controls) and slice 11 D8's provenance-based trust
(the owner's own items don't taint; an invite, a Gmail to-do or a mail still does; + negative
controls) and slice 12 D1's Drive (chosen folders only: 25 path cases, 10 hostile files; + the
parents-check-off and trusted-tools negative controls) and slice 12's Maps and YouTube (Google's
free-allowance ledger, per-message caps, Home / Work, attribution and links on every card, fenced
titles, the owner's playlist grant; + the ledger-off negative control). The exit status is the
gated suites: phase0 --mock is a smoke run and never fails CI.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
SUITES = [
    ("phase0 (smoke)", [sys.executable, str(HERE / "phase0" / "run.py"), "--mock"], False),
    ("slice6 (gated)", [sys.executable, str(HERE / "slice6" / "run.py"), "--mock"], True),
    ("brief (gated)", [sys.executable, str(HERE / "brief" / "run.py"), "--mock"], True),
    ("budget (gated)", [sys.executable, str(HERE / "budget" / "run.py"), "--mock"], True),
    ("memory (gated)", [sys.executable, str(HERE / "memory" / "run.py"), "--mock"], True),
    ("voice (gated)", [sys.executable, str(HERE / "voice" / "run.py"), "--mock"], True),
    ("web (gated)", [sys.executable, str(HERE / "web" / "run.py"), "--mock"], True),
    ("tasks (gated)", [sys.executable, str(HERE / "tasks" / "run.py"), "--mock"], True),
    ("permissions (gated)", [sys.executable, str(HERE / "permissions" / "run.py"), "--mock"], True),
    ("documents (gated)", [sys.executable, str(HERE / "documents" / "run.py"), "--mock"], True),
    ("reminders (gated)", [sys.executable, str(HERE / "reminders" / "run.py"), "--mock"], True),
    ("undo (gated)", [sys.executable, str(HERE / "undo" / "run.py"), "--mock"], True),
    ("approvals (gated)", [sys.executable, str(HERE / "approvals" / "run.py"), "--mock"], True),
    ("trust (gated)", [sys.executable, str(HERE / "trust" / "run.py"), "--mock"], True),
    ("drive (gated)", [sys.executable, str(HERE / "drive" / "run.py"), "--mock"], True),
    ("maps (gated)", [sys.executable, str(HERE / "maps" / "run.py"), "--mock"], True),
    ("youtube (gated)", [sys.executable, str(HERE / "youtube" / "run.py"), "--mock"], True),
]


def main() -> int:
    failed: list[str] = []
    for name, cmd, gated in SUITES:
        print(f"\n===== {name} =====", flush=True)
        rc = subprocess.run(cmd, check=False).returncode
        if gated and rc != 0:
            failed.append(name)
    print("\nALL MOCK EVALS:", "PASS" if not failed else f"FAIL ({', '.join(failed)})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
