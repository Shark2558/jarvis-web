#!/usr/bin/env python3
# scripts/coverage_floor.py
"""R14 D17: the unit tests' coverage, measured and ratcheted towards ECC's 80 % target.

    python scripts/coverage_floor.py --json coverage.json [--floor scripts/coverage_floor.txt]
                                     [--summary FILE]

Reads coverage.py's JSON report (`pytest --cov=jarvis --cov-report=json`), writes one line to
the summary file (CI passes `$GITHUB_STEP_SUMMARY`) and fails only when the total is below the
committed floor, a whole percentage that only ever goes up (the agents' hook refuses a lower one).
Exit 0 = at or above the floor, 1 = below it, 2 = a report or floor that can't be read.
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TARGET = 80.0
HERE = Path(__file__).resolve().parent


def read_total(path: Path) -> float:
    data = json.loads(path.read_text(encoding="utf-8"))
    total = float(data["totals"]["percent_covered"])
    if not 0.0 <= total <= 100.0:
        raise ValueError(f"total out of range: {total}")
    return total


def read_floor(path: Path) -> int:
    text = path.read_text(encoding="utf-8").strip()
    value = int(text)
    if not 0 <= value <= 100:
        raise ValueError(f"floor out of range: {value}")
    return value


def line_for(total: float, floor: int) -> str:
    gap = max(0.0, TARGET - total)
    return (
        f"Coverage (unit tests, Python 3.12): {total:.2f} % · floor {floor} % · target "
        f"{TARGET:.0f} % ({gap:.2f} points to go)"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", type=Path, required=True)
    ap.add_argument("--floor", type=Path, default=HERE / "coverage_floor.txt")
    ap.add_argument("--summary", type=Path, default=None)
    args = ap.parse_args(argv)
    try:
        total, floor = read_total(args.json), read_floor(args.floor)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"coverage: can't read the report or the floor ({type(exc).__name__}: {exc})")
        return 2
    line = line_for(total, floor)
    print(line)
    if args.summary is not None:
        with args.summary.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    if total < floor:
        print(f"coverage: {total:.2f} % is below the floor of {floor} %")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
