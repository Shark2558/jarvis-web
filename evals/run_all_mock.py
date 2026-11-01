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
negative control, provider error mapping, transcribe input validation) and slice 10's attached
documents (extraction limits, recall via doc_search from a 100-page PDF, injection inside a
document + its negative control, training-brain privacy). The exit status is the gated suites:
phase0 --mock is a smoke run and never fails CI.
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
    ("documents (gated)", [sys.executable, str(HERE / "documents" / "run.py"), "--mock"], True),
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
