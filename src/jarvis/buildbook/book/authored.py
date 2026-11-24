# src/jarvis/buildbook/book/authored.py
"""R6.3.1 D1-D6 (docs/plans/r6-3-1-book-at-build.md): the Workshop's written pages and flowcharts,
read, checked and stamped: THE module the generator (part E) and `pages` (gen/pages_cli.py) use.
Paths are the repository's (`root` is the checkout's top).

- The files (`book/files.py`, re-exported here): `PageFile` (front matter + the five sections),
  `FlowSpec` (`book/flow.py`), `load_page`, `load_flow`, `all_pages(root)`, `all_flows(root)`,
  `AuthoredError` (one plain-words error naming the file, never its content), `stamped`.
- `source_hashes(repo, refs)`: ref -> the first 16 hex of the SHA-256 of the checkout's tracked
  file (the basis of `writer/carry.tree_of`); a scrubbed ref ("[removed]" in place of the owner's
  handle) is hashed from the files it can stand for.
- `check_page(page, ip, env, flow=..., flow_error=...)`: every problem, one line each: R6.3's six
  checks (`writer/checks.check`, `canary=""`) in words (`book/explain.py`), the flowchart's
  (required for chapters and modules, node refs among the page's refs, its words past the
  scrubber and the private-word guard) and staleness (`stale: ...`: `sources` must name exactly
  the page's refs, each hash current).
- `status(page, ip, repo, problems)`: "missing" | "stale" | "failing" | "ok" (failing beats stale).
- `judge(root, ip, env)`: all of it from the files of one indexed page -> `Verdict`.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypeVar

from jarvis.buildbook.book import explain
from jarvis.buildbook.book.files import (
    BOOK_DIR,
    FLOW_CAP_BYTES,
    FLOWS,
    HASH_LEN,
    PAGE_CAP_BYTES,
    PAGES,
    AuthoredError,
    FrontMatter,
    Loaded,
    PageFile,
    all_flows,
    all_pages,
    flow_path,
    load_flow,
    load_page,
    page_path,
    plain_errors,
    stamped,
    write_text,
)
from jarvis.buildbook.book.flow import REQUIRED_FOR, FlowSpec
from jarvis.buildbook.facts_model import FactPack, IndexedPage
from jarvis.buildbook.gen.repo import Repo
from jarvis.buildbook.gen.scrub import REMOVED, Scrubber
from jarvis.buildbook.writer import checks

STALE, MISSING = "stale: ", "missing"
STALE_SHOWN = 10
Status = Literal["missing", "stale", "failing", "ok"]
T = TypeVar("T")


# ---- staleness (D2, D6) -------------------------------------------------------------------------
def files_of(repo: Repo, ref: str) -> tuple[str, ...]:
    """The tracked files a page ref stands for: itself, or for a scrubbed ref every file it can
    be ("[removed]" is one or more characters of one path segment)."""
    if repo.has(ref):
        return (ref,)
    if REMOVED not in ref:
        return ()
    head = ref.split(REMOVED, 1)[0]
    pattern = re.compile("[^/]+".join(re.escape(part) for part in ref.split(REMOVED)))
    return tuple(f for f in repo.files if f.startswith(head) and pattern.fullmatch(f))


def _short(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:HASH_LEN]


def source_hashes(repo: Repo, refs: Iterable[str]) -> dict[str, str]:
    """ref -> the first 16 hex of the SHA-256 of its tracked file's bytes (several files: of
    their hashes joined in order); a ref with no readable tracked file is left out."""
    out: dict[str, str] = {}
    for ref in refs:
        files = files_of(repo, ref)
        try:
            digests = [hashlib.sha256(repo.data(f)).hexdigest() for f in files]
        except OSError:
            continue
        if len(files) == 1:
            out[ref] = digests[0][:HASH_LEN]
        elif files:
            out[ref] = _short("".join(digests).encode("ascii"))
    return out


def stale_problems(page: PageFile, ip: IndexedPage, repo: Repo) -> list[str]:
    if not page.sources:
        return [f"{STALE}not stamped yet: run `pages --stamp {ip.id}`"]
    now, found = source_hashes(repo, ip.refs), []
    for ref in ip.refs:
        if ref not in now:
            found.append(f"{STALE}`{ref}` has no tracked file to hash")
        elif ref not in page.sources:
            found.append(f"{STALE}`{ref}` is new to this page")
        elif page.sources[ref] != now[ref]:
            found.append(f"{STALE}`{ref}` changed since the page was stamped")
    gone = sorted(set(page.sources) - set(ip.refs))
    found += [f"{STALE}`{r}` is no longer one of the page's refs" for r in gone]
    if len(found) > STALE_SHOWN:
        found = [*found[:STALE_SHOWN], f"{STALE}and {len(found) - STALE_SHOWN} more refs"]
    return found


# ---- the whole check (D5) -----------------------------------------------------------------------
@dataclass(frozen=True)
class Env:
    """What a check reads besides the files: the tree's fact pack, the scrubber, the checkout and
    the owner's addresses (none at build time unless the environment names them)."""

    facts: FactPack
    scrub: Scrubber
    repo: Repo
    emails: tuple[str, ...] = ()
    sets: dict[str, frozenset[str]] = field(default_factory=dict, compare=False, repr=False)


def page_problems(page: PageFile, ip: IndexedPage, env: Env) -> list[str]:
    ctx = checks.Context(page=ip, facts=env.facts, scrub=env.scrub, emails=env.emails,
                         canary="", _sets=env.sets)  # fmt: skip
    return explain.check_words(checks.check(page.sections, ctx), page.sections, ctx)


def flow_problems(
    ip: IndexedPage, env: Env, flow: FlowSpec | None, flow_error: str | None = None
) -> list[str]:
    if flow_error:
        return [f"flow: {flow_error}"]
    if flow is None:
        if ip.kind not in REQUIRED_FOR:
            return []
        return [f"flow: missing: write flows/{ip.id}.json (every chapter and module has one)"]
    out = []
    for node in flow.nodes:
        if node.ref is not None and node.ref not in ip.refs:
            ref = f"`{node.ref}`" if explain.quotable(node.ref, env.scrub) else "its ref"
            out.append(f"flow: node {node.id}: {ref} is not one of the page's refs")
    for where, text in flow.words():
        kinds = explain.private_kinds(text, env.scrub, env.emails)
        if kinds:
            out.append(f"flow: {where}: {', '.join(kinds)} (no personal data, links or secrets)")
    return out


def check_page(
    page: PageFile | None,
    ip: IndexedPage,
    env: Env,
    *,
    flow: FlowSpec | None = None,
    flow_error: str | None = None,
) -> list[str]:
    """Every problem of a written page, one line each (["missing"] when it isn't written)."""
    if page is None:
        return [MISSING]
    found = page_problems(page, ip, env) + flow_problems(ip, env, flow, flow_error)
    return found + stale_problems(page, ip, env.repo)


def status(
    page: PageFile | None, ip: IndexedPage, repo: Repo, problems: Sequence[str] | None = None
) -> Status:
    """`problems` from `check_page`; without them only missing, stale or ok can be told."""
    if page is None:
        return "missing"
    found = stale_problems(page, ip, repo) if problems is None else problems
    if any(not p.startswith(STALE) for p in found):
        return "failing"
    return "stale" if found else "ok"


@dataclass(frozen=True)
class Verdict:
    status: Status
    problems: tuple[str, ...]
    page: PageFile | None = None


def _try(path: Path, load: Callable[[Path], T]) -> tuple[T | None, str | None]:
    if not path.exists() and not path.is_symlink():
        return None, None
    try:
        return load(path), None
    except AuthoredError as exc:
        return None, str(exc)


def judge(root: Path, ip: IndexedPage, env: Env) -> Verdict:
    """One indexed page's status and problems, from its files under `root`."""
    page, error = _try(page_path(root, ip.id), load_page)
    if error is not None:
        return Verdict("failing", (error,))
    flow, flow_error = _try(flow_path(root, ip.id), load_flow)
    found = check_page(page, ip, env, flow=flow, flow_error=flow_error)
    return Verdict(status(page, ip, env.repo, found), tuple(found), page)


__all__ = [
    "BOOK_DIR",
    "FLOWS",
    "FLOW_CAP_BYTES",
    "MISSING",
    "PAGES",
    "PAGE_CAP_BYTES",
    "STALE",
    "AuthoredError",
    "Env",
    "FlowSpec",
    "FrontMatter",
    "Loaded",
    "PageFile",
    "Status",
    "Verdict",
    "all_flows",
    "all_pages",
    "check_page",
    "files_of",
    "flow_path",
    "flow_problems",
    "judge",
    "load_flow",
    "load_page",
    "page_path",
    "page_problems",
    "plain_errors",
    "source_hashes",
    "stale_problems",
    "stamped",
    "status",
    "write_text",
]
