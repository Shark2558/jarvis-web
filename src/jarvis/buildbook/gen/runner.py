# src/jarvis/buildbook/gen/runner.py
"""`python -m jarvis.buildbook.gen` once its packages import (`__main__` guards that import and
clears an earlier build's files first). Builds, checks and writes the book; on a failure names
the reason in ONE line — a GenError's plain words, or for anything unexpected its type, the file
name it concerns and the code place (`unexpected FileNotFoundError (redact.json) at
buildbook/gen/scrub.py:180`), never an exception's message (it can hold file content) or a path.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from pathlib import Path
from types import TracebackType

from jarvis.buildbook.gen import fallback, licences, write
from jarvis.buildbook.gen.repo import GenError, Repo

DEFAULT_OUT = Path("src") / "jarvis" / "buildbook" / "_book"
DIRTY = (
    "tracked files have uncommitted changes: commit them first, so the book names the code "
    "its commit holds"
)
_PKG = "/jarvis/"


def say(text: str, *, err: bool = False) -> None:
    (sys.stderr if err else sys.stdout).write(text + "\n")


def _where(tb: TracebackType | None) -> str:
    """The innermost code place inside the jarvis package, as `buildbook/gen/scrub.py:180`."""
    frames = [f for f in traceback.extract_tb(tb) if _PKG in f.filename.replace("\\", "/")]
    if not frames:
        return ""
    last = frames[-1]
    return f" at {last.filename.replace(chr(92), '/').rsplit(_PKG, 1)[1]}:{last.lineno}"


def unexpected(exc: BaseException) -> str:
    """One line for an exception best effort didn't expect: type, file name, code place."""
    name = getattr(exc, "filename", None)
    shown = ""
    if isinstance(name, (str, bytes, os.PathLike)) and os.fsdecode(name):
        shown = f" ({Path(os.fsdecode(name)).name})"
    return f"unexpected {type(exc).__name__}{shown}{_where(exc.__traceback__)}"


def _out(args: argparse.Namespace, repo: Repo | None) -> Path | None:
    if args.out is not None:
        return Path(args.out)
    return None if args.check or repo is None else repo.root / DEFAULT_OUT


def _summary(built: write.Built, seconds: float, checked: bool) -> str:
    r = built.release
    head = f"build book {r.label} ({r.id}): book.json {len(built.book):,} bytes, "
    tail = f"source.zip {len(built.source):,} bytes, {r.skipped} files left out, {seconds:.1f} s"
    return head + tail + ("; two builds are byte-identical" if checked else "")


def _fail(args: argparse.Namespace, repo: Repo | None, message: str) -> int:
    say(f"build book failed: {message}", err=True)
    out = _out(args, repo)
    if out is not None:
        fallback.clear(out)  # never leave an earlier book beside a failed build
    if not args.best_effort:
        return 1
    if repo is not None and out is not None:
        write.write_error(out, repo, message)
        say(f"build book: wrote {write.RELEASE_FILE} with the error; no book", err=True)
    return 0


def _licences(args: argparse.Namespace) -> int:
    try:
        count = licences.write_table(Repo.from_git(args.repo))
    except GenError as exc:
        say(f"licence table not written: {exc}", err=True)
        return 1
    say(f"{licences.TABLE}: {count} packages")
    return 0


def run(args: argparse.Namespace) -> int:
    if getattr(args, "licences", False):
        return _licences(args)
    started, repo = time.monotonic(), None
    try:
        repo = Repo.from_git(args.repo)
        out = _out(args, repo)
        if out is not None and repo.dirty:
            raise GenError(DIRTY)
        built = write.check(repo) if args.check else write.build(repo)
        if out is not None:
            write.write(out, built)
    except GenError as exc:
        return _fail(args, repo, str(exc))
    except Exception as exc:  # noqa: BLE001 - best effort must never break a deploy
        if not args.best_effort:
            raise
        return _fail(args, repo, unexpected(exc))
    say(_summary(built, time.monotonic() - started, args.check))
    return 0


__all__ = ["DEFAULT_OUT", "DIRTY", "run", "say", "unexpected"]
