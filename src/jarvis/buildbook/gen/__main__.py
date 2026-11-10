# src/jarvis/buildbook/gen/__main__.py
"""`python -m jarvis.buildbook.gen` — write the build book of the checkout (R6 D2-D5).

    --repo DIR      the checkout (default: the git checkout around the working folder)
    --out DIR       where book.json, source.zip and release.json go (default:
                    <repo>/src/jarvis/buildbook/_book; with --check, nothing is written unless
                    --out is given)
    --check         build twice and refuse if the bytes differ (the CI gate on every PR)
    --best-effort   never fail (the deploy job, `make book`): on an error write a release.json
                    that names it and no book, and exit 0 so the deploy goes on

The summary names sizes and timings only; never book text, a secret or a name.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from jarvis.buildbook.gen import write
from jarvis.buildbook.gen.repo import GenError, Repo

DEFAULT_OUT = Path("src") / "jarvis" / "buildbook" / "_book"


def _args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="python -m jarvis.buildbook.gen", description=__doc__)
    ap.add_argument("--repo", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--best-effort", action="store_true")
    return ap.parse_args(argv)


def _say(text: str, *, err: bool = False) -> None:
    (sys.stderr if err else sys.stdout).write(text + "\n")


def _summary(built: write.Built, seconds: float, checked: bool) -> str:
    r = built.release
    head = f"build book {r.label} ({r.id}): book.json {len(built.book):,} bytes, "
    tail = f"source.zip {len(built.source):,} bytes, {r.skipped} files left out, {seconds:.1f} s"
    return head + tail + ("; two builds are byte-identical" if checked else "")


def _fail(args: argparse.Namespace, repo: Repo | None, message: str) -> int:
    _say(f"build book failed: {message}", err=True)
    if not args.best_effort:
        return 1
    if repo is not None:
        out = args.out or repo.root / DEFAULT_OUT
        write.write_error(out, repo, message)
        _say(f"build book: wrote {out / write.RELEASE_FILE} with the error; no book", err=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _args(argv)
    started, repo = time.monotonic(), None
    try:
        repo = Repo.from_git(args.repo)
        built = write.check(repo) if args.check else write.build(repo)
        out = args.out or (None if args.check else repo.root / DEFAULT_OUT)
        if out is not None:
            write.write(out, built)
    except GenError as exc:
        return _fail(args, repo, str(exc))
    except Exception as exc:  # noqa: BLE001 - best effort must never break a deploy
        if not args.best_effort:
            raise
        return _fail(args, repo, f"unexpected {type(exc).__name__}")
    _say(_summary(built, time.monotonic() - started, args.check))
    return 0


if __name__ == "__main__":
    sys.exit(main())
