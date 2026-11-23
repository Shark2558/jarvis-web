# src/jarvis/buildbook/gen/facts_cache.py
"""R6.3.1 D5 (docs/plans/r6-3-1-book-at-build.md): the fact pack `pages` checks against, built
once per tree and kept in `build/book-cache/facts-<key>.json` (git-ignored), so a check takes
seconds instead of the half minute a build takes.

The key is the SHA-256 over every documented tracked file's path and bytes (`Repo.files`: the
generator's own view, which leaves out the Book's pages and flowcharts), this cache's format
and the Python minor version (the scanners read its AST). So writing a page never invalidates
the pack, while any change to the code, the guide or the plans does, committed or not. A cached
file that won't load (cut short, edited) is built again; the newest `KEEP` trees are kept.
`build_pack` is the generator's own join (`write.fact_pack`) with this checkout's release.
"""

from __future__ import annotations

import hashlib
import os
import sys
from collections.abc import Callable
from pathlib import Path

from jarvis.buildbook.facts_model import FactPack, canonical_facts, load_facts
from jarvis.buildbook.gen import plans, write
from jarvis.buildbook.gen.repo import Repo
from jarvis.buildbook.gen.scrub import default_scrubber
from jarvis.buildbook.model import ReleaseRef

CACHE_DIR = Path("build") / "book-cache"
KEEP = 4  # trees kept (a writer's branch and main, before and after a merge)
FORMAT = 1  # bump when what is cached changes shape without a tracked file changing
KEY_HEX = 32
Builder = Callable[[Repo], FactPack]


def key(repo: Repo) -> str:
    v = sys.version_info
    digest = hashlib.sha256(f"facts-cache v{FORMAT} py{v.major}.{v.minor}\n".encode("ascii"))
    for rel in repo.files:
        digest.update(rel.encode("utf-8") + b"\0")
        try:
            digest.update(hashlib.sha256(repo.data(rel)).digest())
        except OSError:
            digest.update(b"unreadable\0")
    return digest.hexdigest()[:KEY_HEX]


def path_for(repo: Repo) -> Path:
    return repo.root / CACHE_DIR / f"facts-{key(repo)}.json"


def build_pack(repo: Repo) -> FactPack:
    """The pack the generator would join for this checkout (GenError when it can't)."""
    release = ReleaseRef(
        id=repo.id,
        sha=repo.sha,
        label=plans.release_label(repo),
        committed_at=repo.committed_at,
        version=write.release_version(repo),
    )
    return write.fact_pack(repo, release, default_scrubber())


def _prune(folder: Path, keep: Path) -> None:
    try:
        older = [p for p in folder.glob("facts-*.json") if p != keep]
        older.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for stale in older[KEEP - 1 :]:
            stale.unlink(missing_ok=True)
    except OSError:
        return  # a cache that can't be tidied is still a cache


def facts_for(
    repo: Repo, build: Builder = build_pack, note: Callable[[], None] | None = None
) -> tuple[FactPack, bool]:
    """(the tree's pack, whether it came from the cache); `note` is called before a build."""
    path = path_for(repo)
    try:
        return load_facts(path.read_bytes()), True
    except (OSError, ValueError):
        pass
    if note is not None:
        note()
    pack = build(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(canonical_facts(pack))
    os.replace(tmp, path)
    _prune(path.parent, path)
    return pack, False


__all__ = ["CACHE_DIR", "KEEP", "Builder", "build_pack", "facts_for", "key", "path_for"]
