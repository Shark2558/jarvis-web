# src/jarvis/buildbook/gen/fallback.py
"""R6 D4 best effort that works when the generator itself can't run: STANDARD LIBRARY ONLY.

    clear(out)                      unlink an earlier build's book.json, source.zip, release.json
                                    (and their temp files), so a stale `_book/` is never served
                                    as this release; nothing else in `out` is touched
    error_release(start, out, msg)  a release.json that names the error and no book, from git
                                    alone (no pydantic): the deploy's `pip install` failed, yet the
                                    app still learns that this release has no book
                                    (`book_seal_failed`) instead of serving nothing silently
    label_of(path)                  "R6" / "R5.1" from a plan's file name (shared with gen.plans)

The bytes are the ones `write.release_bytes` writes for the same release (a test pins it).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

BOOK_FILES = ("book.json", "source.zip")
RELEASE_FILE = "release.json"
PLANS = "docs/plans/"
ERROR_MAX = 200
GIT_TIMEOUT_S = 30
RELEASE_PLAN = re.compile(r"^r(\d{1,3})(?:-(\d{1,2}))?-")


def clear(out: Path) -> None:
    if not out.is_dir():
        return
    for name in (*BOOK_FILES, RELEASE_FILE):
        for path in (out / name, out / f".{name}.tmp"):
            path.unlink(missing_ok=True)


def label_of(path: str) -> str:
    m = RELEASE_PLAN.match(path.rsplit("/", 1)[-1])
    if not m:
        return ""
    return f"R{int(m.group(1))}" + (f".{int(m.group(2))}" if m.group(2) else "")


def _release_key(path: str) -> tuple[int, int]:
    m = RELEASE_PLAN.match(path.rsplit("/", 1)[-1])
    return (int(m.group(1)), int(m.group(2) or 0)) if m else (-1, -1)


def _git(root: Path, *args: str) -> str | None:
    try:
        done = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, timeout=GIT_TIMEOUT_S, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return os.fsdecode(done.stdout)


def _label(top: Path) -> str:
    listed = (_git(top, "ls-files", "-z", "--", PLANS) or "").split("\0")
    plans = [p for p in listed if p.endswith(".md") and p.count("/") == 2 and label_of(p)]
    return label_of(max(plans, key=_release_key)) if plans else "R0"


def release_doc(sha: str, label: str, committed_at: str, error: str) -> bytes:
    """release.json for a failed build, as `write.release_bytes` formats it."""
    doc = {
        "book_sha256": None,
        "committed_at": committed_at,
        "error": " ".join(error.split())[:ERROR_MAX] or "the build book failed",
        "id": sha[:7],
        "label": label,
        "sha": sha,
        "skipped": 0,
        "source_bytes": 0,
        "source_sha256": None,
        "v": 1,
    }
    return (json.dumps(doc, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def error_release(start: Path, out: Path | None, error: str) -> Path | None:
    """Write the error release.json (None: no commit to name, or no folder to write to)."""
    top = (_git(start, "rev-parse", "--show-toplevel") or "").strip()
    if not top:
        return None
    sha = (_git(Path(top), "rev-parse", "HEAD") or "").strip()
    when = (_git(Path(top), "log", "-1", "--format=%cI") or "").strip()
    if not (re.fullmatch(r"[0-9a-f]{40}", sha) and when):
        return None
    target = out if out is not None else Path(top) / "src" / "jarvis" / "buildbook" / "_book"
    target.mkdir(parents=True, exist_ok=True)
    clear(target)
    tmp = target / f".{RELEASE_FILE}.tmp"
    tmp.write_bytes(release_doc(sha, _label(Path(top)), when, error))
    os.replace(tmp, target / RELEASE_FILE)
    return target / RELEASE_FILE


__all__ = ["BOOK_FILES", "RELEASE_FILE", "clear", "error_release", "label_of", "release_doc"]
