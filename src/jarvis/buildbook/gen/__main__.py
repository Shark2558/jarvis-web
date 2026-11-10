# src/jarvis/buildbook/gen/__main__.py
"""`python -m jarvis.buildbook.gen` — write the build book of the checkout (R6 D2-D5).

    --repo DIR      the checkout (default: the git checkout around the working folder)
    --out DIR       where book.json, source.zip and release.json go (default:
                    <repo>/src/jarvis/buildbook/_book; with --check, nothing is written unless
                    --out is given)
    --check         build twice and refuse if the bytes differ (the CI gate on every PR)
    --best-effort   never fail (the deploy job, `make book`): on an error write a release.json
                    that names it and no book, and exit 0 so the deploy goes on
    --licences      rewrite requirements.licences.json from the installed dists (run with
                    requirements.lock installed; refuses if any installed version differs)

An earlier build's files in --out are removed FIRST, so a stale book is never served as this
release. This module and `fallback` import the standard library only: when the generator's own
packages are missing (the deploy's `pip install` failed), best effort still writes a release.json
naming that, from git alone. A dirty checkout is never written as its commit. The summary names
sizes and timings only; never book text, a secret or a name.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jarvis.buildbook.gen import fallback


def _args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="python -m jarvis.buildbook.gen", description=__doc__)
    ap.add_argument("--repo", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--best-effort", action="store_true")
    ap.add_argument("--licences", action="store_true")
    return ap.parse_args(argv)


def _without_packages(args: argparse.Namespace, exc: ImportError) -> int:
    missing = exc.name or "a package"
    message = f"the build book's Python packages aren't installed ({missing})"
    sys.stderr.write(f"build book failed: {message}\n")
    if not args.best_effort:
        return 1
    if args.out is not None or not args.check:
        start = args.repo or Path.cwd()
        if fallback.error_release(start, args.out, message) is not None:
            sys.stderr.write(f"build book: wrote {fallback.RELEASE_FILE} with the error\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _args(argv)
    if args.out is not None:
        fallback.clear(args.out)  # an earlier build's files never pass as this one's
    try:
        from jarvis.buildbook.gen import runner
    except ImportError as exc:
        return _without_packages(args, exc)
    return runner.run(args)


if __name__ == "__main__":
    sys.exit(main())
