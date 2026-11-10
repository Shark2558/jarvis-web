# evals/r6_book/run.py
"""R6 mock evals, the build book (docs/plans/r6-build-book.md "Evals and tests"). One suite file per
part, run in this order:

    gen.py     (A)  double build byte-equal; scrub; secret scan; 16 MB refused; flows; licences
    seal.py    (B)  two releases sealed + notices; retention 3; tamper fails closed; one racing seal
    access.py  (C)  stale sign-in, no proof, no passkey, bearer, a vault proof, expired / idle token
    guest.py   (C)  a worst-case mock brain: owner-data asks refused with NO provider call, ...
    wipe.py    (C)  after close a needle question is nowhere; content-free notice and audit
    lock.py    (C)  the guest lock over every cookie session; only a book_resume passkey lifts it

    python evals/r6_book/run.py --mock [--require-all]

Each suite file defines `main() -> int`: 0 only when every case passed AND each negative control
made its suite fail (r1d_common.finish). It writes its report with
`finish(REPORTS / "<suite>", "r6_book_<suite>", results, control)` (REPORTS = evals/r6_book/reports;
git-ignored like every evals/**/report.json). R6 I0: no suite exists yet, so each is "not built
yet" and the run passes; I1 adds `--require-all` in evals/run_all_mock.py once A-C are merged, so a
missing suite then fails the gate.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
REPORTS = HERE / "reports"
SUITES: tuple[tuple[str, str], ...] = (
    ("gen", "A"),
    ("seal", "B"),
    ("access", "C"),
    ("guest", "C"),
    ("wipe", "C"),
    ("lock", "C"),
)
for extra in (HERE.parent, ROOT / "tests", ROOT / "src"):  # r1d_common, the shared fakes, jarvis
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))


def _run_suite(name: str) -> int:
    """Load evals/r6_book/<name>.py under its own module name and run its main()."""
    spec = importlib.util.spec_from_file_location(f"r6_book_{name}", HERE / f"{name}.py")
    if spec is None or spec.loader is None:
        print(f"{name}: can't be loaded")
        return 1
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    rc = module.main()
    return rc if isinstance(rc, int) else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="the only mode (CI)")
    ap.add_argument("--require-all", action="store_true", help="a missing suite fails the run")
    args = ap.parse_args()
    failed: list[str] = []
    missing: list[str] = []
    for name, part in SUITES:
        if not (HERE / f"{name}.py").is_file():
            missing.append(name)
            print(f"{name}: not built yet (part {part})")
            continue
        print(f"--- r6_book {name} (part {part}) ---", flush=True)
        if _run_suite(name) != 0:
            failed.append(name)
    ran = len(SUITES) - len(missing)
    bad = failed + (missing if args.require_all else [])
    print(f"r6_book: {ran - len(failed)}/{ran} suites passed; not built yet: {missing or 'none'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
