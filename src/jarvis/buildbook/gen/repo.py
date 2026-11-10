# src/jarvis/buildbook/gen/repo.py
"""The repository the generator documents (R6 D2, D5): its git-tracked files, commit and date.

Only four git questions are asked, so a SHALLOW clone works (CI's checkout, the sandbox):
`git ls-files -z`, `git rev-parse HEAD`, `git log -1 --format=%cI` and `git status -uno` (`dirty`:
the CLI refuses to WRITE a book for a commit whose tracked files were changed, since the book
would then describe code that commit doesn't hold). Never a history walk. A git failure names
git's first line, paths taken out.
`Repo.from_dir` builds the same view from a plain folder with a given commit (tests only).
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from jarvis.buildbook.model import BOOK_JSON_CAP_BYTES

GIT_TIMEOUT_S = 30
GIT_SAID_MAX = 120
# a quoted string or an absolute path in git's words (it can name the owner's home folder)
_PATH = re.compile(r"'[^']*'|\"[^\"]*\"|(?:[A-Za-z]:)?[\\/][^\s:]*")
TEXT_CAP_BYTES = 4 * BOOK_JSON_CAP_BYTES  # a single file read as text (plans, sources)


class GenError(Exception):
    """The book can't be built honestly. Plain words; never book text, a secret or a name."""


def _said(stderr: bytes | None) -> str:
    """git's first stderr line with any path taken out ("fatal: not a git repository ...")."""
    text = os.fsdecode(stderr or b"")
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    line = _PATH.sub("<path>", line)
    return line[:GIT_SAID_MAX]


def _verb(args: tuple[str, ...]) -> str:
    return next((a for a in args if not a.startswith("-")), "")


def _git(root: Path, *args: str) -> str:
    try:
        done = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            timeout=GIT_TIMEOUT_S,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        said = _said(exc.stderr)
        raise GenError(f"git {_verb(args)} failed" + (f": {said}" if said else "")) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        why = "git can't run here" if isinstance(exc, OSError) else "git timed out"
        raise GenError(f"git {_verb(args)} failed: {why}") from exc
    return os.fsdecode(done.stdout)


def _plain_file(top: Path, path: Path) -> bool:
    """A regular file inside the checkout: a symlink is never followed (it could point anywhere,
    and the snapshot must hold only the checkout's own files)."""
    if path.is_symlink() or not path.is_file():
        return False
    return path.resolve().is_relative_to(top.resolve())


@dataclass(frozen=True)
class Repo:
    """A checkout: `files` are POSIX paths relative to `root`, sorted, as they are on disk (the
    snapshot normalises the names it writes to NFC)."""

    root: Path
    files: tuple[str, ...]
    sha: str
    committed_at: str
    dirty: bool = False  # tracked files differ from the commit (staged or not)

    @property
    def id(self) -> str:
        return self.sha[:7]

    @classmethod
    def from_git(cls, root: Path | None = None) -> Repo:
        start = (root or Path.cwd()).resolve()
        top = Path(_git(start, "rev-parse", "--show-toplevel").strip())
        listed = _git(top, "ls-files", "-z").split("\0")
        files = tuple(sorted({f for f in listed if f and _plain_file(top, top / f)}))
        sha = _git(top, "rev-parse", "HEAD").strip()
        when = _git(top, "log", "-1", "--format=%cI").strip()
        changed = _git(top, "--no-optional-locks", "status", "--porcelain", "-uno", "-z")
        return cls(root=top, files=files, sha=sha, committed_at=when, dirty=bool(changed))

    @classmethod
    def from_dir(cls, root: Path, *, sha: str, committed_at: str) -> Repo:
        found = (p for p in root.rglob("*") if _plain_file(root, p) and ".git" not in p.parts)
        files = tuple(sorted(p.relative_to(root).as_posix() for p in found))
        return cls(root=root, files=files, sha=sha, committed_at=committed_at)

    def has(self, rel: str) -> bool:
        return rel in self._index

    def under(self, prefix: str) -> tuple[str, ...]:
        """Tracked files below a folder (`prefix` ends with '/'), in order."""
        return tuple(f for f in self.files if f.startswith(prefix))

    def data(self, rel: str) -> bytes:
        return (self.root / rel).read_bytes()

    def size(self, rel: str) -> int:
        return (self.root / rel).stat().st_size

    def text(self, rel: str) -> str | None:
        """UTF-8 text of a tracked file; None when absent, too big or not text."""
        if not self.has(rel) or self.size(rel) > TEXT_CAP_BYTES:
            return None
        try:
            return self.data(rel).decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    @cached_property
    def _index(self) -> frozenset[str]:
        return frozenset(self.files)


__all__ = ["GenError", "Repo"]
