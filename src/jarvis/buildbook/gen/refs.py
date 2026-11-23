# src/jarvis/buildbook/gen/refs.py
"""R6.3 seam 17 (docs/plans/r6-3-book-content.md D3, plan review H5): the ONE rule that turns the
code spans of a guide cell ("Where in the code") into repository paths, moved here unchanged from
`scripts/arch_files.py` `cited` so the guide's check and the full book's pages index agree.

A span is a path when it holds a `/`, ends in a known extension, or is `Dockerfile` / `Makefile`.
A span starting with a top-level folder (`src/`, `deploy/`, ...) is taken from the repository root;
any other is looked up next to the previous hit in the same cell, then in the console's static
folder, `src/jarvis/api`, `src/jarvis` and the root: the first that exists wins (a `*` is a glob
that must match). `resolve` gives each span with its repository-relative POSIX path (a folder
ends in `/`), or None when nothing exists. Standard library only.
"""

from __future__ import annotations

import re
from pathlib import Path

SPAN = re.compile(r"`([^`\s]+)`")
ROOTS = ("src/", "deploy/", "scripts/", "tests/", "evals/", "docs/", ".github/", "home/")
EXT = re.compile(r"\.(?:py|js|html|css|sh|yml|yaml|json|lock|toml|md|txt|cfg|conf)$")
ROOT_FILES = frozenset({"Dockerfile", "Makefile"})
STATIC = "src/jarvis/api/static"


def is_path(span: str) -> bool:
    return "/" in span or bool(EXT.search(span)) or span in ROOT_FILES


def _exists(path: Path) -> bool:
    if "*" in path.name:
        return any(path.parent.glob(path.name))
    return path.exists()


def _candidates(repo: Path, base: Path, span: str) -> list[Path]:
    if span.startswith(ROOTS):
        return [repo / span]
    bases = (base, repo / STATIC, repo / "src/jarvis/api", repo / "src/jarvis", repo)
    return [b / span for b in bases]


def _shown(repo: Path, hit: Path) -> str:
    rel = hit.relative_to(repo).as_posix()
    return rel + "/" if "*" not in hit.name and hit.is_dir() else rel


def resolve(repo: Path, where: str) -> list[tuple[str, str | None]]:
    """Each path span of `where`, in order, with the path it names (None: nothing exists)."""
    out: list[tuple[str, str | None]] = []
    base = repo / "src/jarvis"
    for span in (s for s in SPAN.findall(where) if is_path(s)):
        hit = next((p for p in _candidates(repo, base, span) if _exists(p)), None)
        if hit is None:
            out.append((span, None))
            continue
        out.append((span, _shown(repo, hit)))
        base = hit if "*" not in hit.name and hit.is_dir() else hit.parent
    return out


__all__ = ["ROOTS", "ROOT_FILES", "SPAN", "STATIC", "is_path", "resolve"]
