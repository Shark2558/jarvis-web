#!/usr/bin/env python3
# scripts/check_doc_versions.py
"""R6.1 D4 (acceptance check 3): every plan and architecture document is versioned.

Each `docs/plans/*.md` and `docs/architecture/*.md` (not their sub-folders) must:

  1. open with its version line, as its FIRST line:
       Version v6.1.1 · 11 Nov 2026, 12:00 IST · Release R6.1 · Status: Current · Owner: 🛠 Mark XIII
     (the time is optional: "Version v0.9.0 · 1 Nov 2026 · Release Slice 9 · ...");
  2. end with its change log: the last "## " heading is "## Change log" (a number before it is
     fine), holding the table "| Version | Date | Release | What changed | By |" with one row or
     more, each row's first cell a version such as v6.1.1.

    python3 scripts/check_doc_versions.py [--root DIR]   exit 0 when all pass, 1 with the list

CI's test job runs it (never the deploy job). Standard library only.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

FOLDERS = ("docs/plans", "docs/architecture")
_MONTH = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
VERSION_LINE = re.compile(
    rf"^Version v\d+\.\d+\.\d+ · \d{{1,2}} (?:{_MONTH}) \d{{4}}(?:, \d{{1,2}}:\d{{2}} IST)?"
    r" · Release [^·\s][^·]* · Status: [^·\s][^·]* · Owner: \S.*$",
    re.ASCII,
)
H2 = re.compile(r"^##\s+\S")
LOG_HEADING = re.compile(r"^##\s+(?:\d+(?:\.\d+)*\.?\s+)?Change log\s*$", re.IGNORECASE)
LOG_COLUMNS = ["Version", "Date", "Release", "What changed", "By"]
ROW_VERSION = re.compile(r"^v\d+\.\d+\.\d+$", re.ASCII)
SEPARATOR = re.compile(r"^:?-{3,}:?$")

EXAMPLE_LINE = (
    "Version v6.1.1 · 11 Nov 2026, 12:00 IST · Release R6.1 · Status: Current · Owner: 🛠 Mark XIII"
)
NO_LINE = f"missing the version line: line 1 must read like '{EXAMPLE_LINE}'"
NO_LOG = (
    "missing the change log: end with '## Change log' and the table "
    "'| Version | Date | Release | What changed | By |' with one row or more"
)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _log_ok(lines: list[str]) -> bool:
    heads = [i for i, ln in enumerate(lines) if H2.match(ln)]
    if not heads or not LOG_HEADING.match(lines[heads[-1]]):
        return False  # no change log, or another section after it
    table = [ln for ln in lines[heads[-1] + 1 :] if ln.lstrip().startswith("|")]
    if len(table) < 3 or _cells(table[0]) != LOG_COLUMNS:
        return False
    if not all(SEPARATOR.match(c) for c in _cells(table[1])):
        return False
    rows = [_cells(ln) for ln in table[2:]]
    return all(len(r) == len(LOG_COLUMNS) and ROW_VERSION.match(r[0]) for r in rows)


def problems(text: str) -> list[str]:
    """What one document is missing (an empty list: it passes)."""
    lines = text.splitlines()
    found = []
    if not lines or not VERSION_LINE.match(lines[0]):
        found.append(NO_LINE)
    if not _log_ok(lines):
        found.append(NO_LOG)
    return found


def documents(root: Path) -> list[Path]:
    return sorted(p for folder in FOLDERS for p in (root / folder).glob("*.md") if p.is_file())


def check(root: Path) -> dict[str, list[str]]:
    """{path relative to root: problems} for every document that doesn't pass."""
    out = {}
    for path in documents(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            out[path.relative_to(root).as_posix()] = [f"unreadable ({type(exc).__name__})"]
            continue
        found = problems(text)
        if found:
            out[path.relative_to(root).as_posix()] = found
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="check_doc_versions.py", description=__doc__.split("\n")[0])
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = ap.parse_args(argv)
    docs = documents(args.root)
    if not any(p.parent.name == "plans" for p in docs):
        print(f"no docs/plans/*.md under {args.root}: nothing to check is an error")
        return 1
    found = check(args.root)
    for rel, said in found.items():
        for problem in said:
            print(f"{rel}: {problem}")
    if found:
        print(f"{len(found)} of {len(docs)} documents need their version line or change log.")
        return 1
    print(f"All {len(docs)} documents have their version line and change log.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
