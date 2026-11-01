# evals/run_all_mock.py
"""Run every eval suite against the mock provider (CI plumbing + safety gates).

    python evals/run_all_mock.py

Equivalent to `make eval-mock` once the Makefile points here: phase0 (core loop plumbing),
slice6 (calendar correctness over a fixture + the injection suite, whose gates are hard) and the
slice 7 morning brief (due-logic, composed facts, AI-line injection containment + its negative
control). The exit status is the gated suites: phase0 --mock is a smoke run and never fails CI.
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
