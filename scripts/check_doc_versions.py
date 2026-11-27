#!/usr/bin/env python3
# scripts/check_doc_versions.py
"""R6.1 D4 (acceptance check 3): every plan and architecture document is versioned.

Each `docs/plans/*.md` and `docs/architecture/*.md` (no sub-folder) must, and so must each
chapter (`*.md`) of the Architecture Design Document when its folder is given:

  1. open with its version line, as its FIRST line:
       Version v6.1.1 · 11 Nov 2026, 12:00 IST · Release R6.1 · Status: Current · Owner: 🛠 Mark XIII
     (the time is optional: "Version v0.9.0 · 1 Nov 2026 · Release Slice 9 · ...");
  2. end with its change log: the last "## " heading is "## Change log" (a number before it is
     fine), holding the table "| Version | Date | Release | What changed | By |" with one row or
     more, each row's first cell a version such as v6.1.1. A line may come before the table;
     nothing but table rows after it. Lines inside fenced code (``` or ~~~) are never headings.

    python3 scripts/check_doc_versions.py [--root DIR] [--add-dir DIR]
        exit 0 when all pass, 1 with the list

The Architecture Design Document is kept privately on the owner's Drive, not in the repository:
its folder comes from `--add-dir` or the environment variable `JARVIS_ADD_DIR`. When neither names
a folder that is there, its chapters are skipped with one line and the other documents are checked
as always (CI has no private copy, so it never fails for want of one).

CI's docs-check job runs it once on every pull request and every push to main; no job waits for
that one, so a missing version line never holds up a deploy. Standard library only.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

FOLDERS = ("docs/plans", "docs/architecture")
ADD_ENV = "JARVIS_ADD_DIR"  # the private copy of the Architecture Design Document's chapters
ADD_SKIPPED = (
    "check_doc_versions: the Architecture Design Document's chapters skipped (its private copy"
    f" isn't here: pass --add-dir DIR or set {ADD_ENV})"
)
_MONTH = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
VERSION_LINE = re.compile(
    rf"^Version v\d+\.\d+\.\d+ · \d{{1,2}} (?:{_MONTH}) \d{{4}}(?:, \d{{1,2}}:\d{{2}} IST)?"
    r" · Release [^·\s][^·]* · Status: [^·\s][^·]* · Owner: \S.*$",
    re.ASCII,
)
H2 = re.compile(r"^##\s+\S")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")  # CommonMark: up to 3 spaces, then 3+ ` or ~
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


def _closes(line: str, fence: str) -> bool:
    """A closing fence: the opening's character, at least as long, nothing after it."""
    m = FENCE.match(line)
    return (
        m is not None
        and m.group(1)[0] == fence[0]
        and len(m.group(1)) >= len(fence)
        and not line[m.end() :].strip()
    )


def _unfenced(lines: list[str]) -> list[int]:
    """Indices of the lines outside fenced code blocks (a fence left open runs to the end)."""
    out, fence = [], ""
    for i, ln in enumerate(lines):
        if fence:
            fence = "" if _closes(ln, fence) else fence
        elif m := FENCE.match(ln):
            fence = m.group(1)
        else:
            out.append(i)
    return out


def _table(body: list[str]) -> list[str] | None:
    """The change log's table: from its first row to the end, every line a row (trailing blank
    lines aside), or None when there is no table or something else follows it."""
    rows = [i for i, ln in enumerate(body) if ln.lstrip().startswith("|")]
    if not rows:
        return None
    end = max(i for i, ln in enumerate(body) if ln.strip()) + 1
    table = body[rows[0] : end]
    return table if all(ln.lstrip().startswith("|") for ln in table) else None


def _log_ok(lines: list[str]) -> bool:
    heads = [i for i in _unfenced(lines) if H2.match(lines[i])]
    if not heads or not LOG_HEADING.match(lines[heads[-1]]):
        return False  # no change log, or another section after it
    table = _table(lines[heads[-1] + 1 :])
    if table is None or len(table) < 3 or _cells(table[0]) != LOG_COLUMNS:
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


def add_folder(given: Path | None = None) -> Path | None:
    """The Architecture Design Document's folder: `given`, else `JARVIS_ADD_DIR`; None when
    neither names a folder that is there."""
    env = os.environ.get(ADD_ENV, "").strip()
    folder = given if given is not None else (Path(env).expanduser() if env else None)
    return folder if folder is not None and folder.is_dir() else None


def documents(root: Path, add_dir: Path | None = None) -> list[Path]:
    """The repository's plans and architecture documents, then the ADD's chapters (if given)."""
    folders = [root / f for f in FOLDERS] + ([add_dir] if add_dir is not None else [])
    return sorted(p for folder in folders for p in folder.glob("*.md") if p.is_file())


def _shown(path: Path, root: Path) -> str:
    """A document's name in the report: relative to root, or its own path outside it."""
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else path.as_posix()


def check(root: Path, add_dir: Path | None = None) -> dict[str, list[str]]:
    """{document: problems} for every document that doesn't pass (relative to root)."""
    out = {}
    for path in documents(root, add_dir):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            out[_shown(path, root)] = [f"unreadable ({type(exc).__name__})"]
            continue
        found = problems(text)
        if found:
            out[_shown(path, root)] = found
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="check_doc_versions.py", description=__doc__.split("\n")[0])
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument(
        "--add-dir", type=Path, default=None, help=f"the ADD's chapters (default: ${ADD_ENV})"
    )
    args = ap.parse_args(argv)
    add = add_folder(args.add_dir)
    if not any(p.is_file() for p in (args.root / "docs/plans").glob("*.md")):
        print(f"no docs/plans/*.md under {args.root}: nothing to check is an error")
        return 1
    if add is None:
        print(ADD_SKIPPED)
    docs = documents(args.root, add)
    found = check(args.root, add)
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
