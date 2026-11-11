#!/usr/bin/env python3
# scripts/check_pr_title.py
"""R6.1 D4: a pull request's title names its version, its release and the Mark that built it.

    v6.1.0 · R6.1 The Architecture Guide & versioning · Mark XIII
    v0.12.0 · Slice 12 Drive, Maps, YouTube, Contacts and WhatsApp drafts · Mark VII–VIII

    python3 scripts/check_pr_title.py "<title>"   exit 0 when it matches, 1 when not, 2 on usage

The separators are the middle dot " · " and, between two Marks, the en dash "–". CI's `pr-title`
job runs this on pull requests only (Dependabot's are exempt); the deploy job never waits for it.
Standard library only. The title is never echoed at the start of a line (a line starting with
"::" would be a GitHub workflow command).
"""

from __future__ import annotations

import re
import sys

TITLE = r"^v\d+\.\d+\.\d+ · .+ · Mark [IVXLC]+(–[IVXLC]+)?$"
PATTERN = re.compile(TITLE, re.ASCII)  # ASCII: \d is 0-9 only
EXAMPLE = "v6.1.0 · R6.1 Short name · Mark XIII"


def check(title: str) -> bool:
    """True when the whole title matches (a trailing newline or space does not)."""
    return PATTERN.fullmatch(title) is not None


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        sys.stderr.write('usage: check_pr_title.py "<pull request title>"\n')
        return 2
    title = argv[0]
    if check(title):
        print(f"PR title OK: {title!r}")
        return 0
    print(f"::error title=Pull request title::The title must read like '{EXAMPLE}'.")
    print(f"PR title given: {title!r}")
    print("Version, then the release and its short name, then the Mark that built it, joined by")
    print("' · ' (a middle dot with a space each side); two Marks are joined by '–' (an en dash).")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
