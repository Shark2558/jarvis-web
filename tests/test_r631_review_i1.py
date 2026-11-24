# tests/test_r631_review_i1.py
"""R6.3.1 combined review of I1 (docs/plans/r6-3-1-integration/REVIEW-I1.md): the fixes, each
pinned by the test written before it.

- M-1: a page or flowchart file that is a symbolic link is refused (never followed), whether it
  is read through the folder (`all_pages`) or by its page id (`judge`, the generator's compile).
- M-2: a front matter or a flowchart nested past Python's recursion limit is ONE plain-words
  `AuthoredError`, and a page whose checks break in any other way is the generator's text: one
  page never takes the whole full book (or the tour and the seal) down with it (D4).
- M-3: the sealed code snapshot holds the Book's own folder too (its modules `jarvis.buildbook.
  book.*`, the guide, the pages and flows), though the index, the refs and the facts never do.
- L-1: a pages or flows file whose bytes break in a way the gzip or JSON layer reports with its
  own error (a bad deflate block, nesting too deep) is a ValueError, so serving it is 503
  `unavailable` and sealing it is refused, never a bare 500 or a crashed seal run.
"""

from __future__ import annotations

import gzip
import io
import zipfile
from pathlib import Path
from typing import Any

import pytest
from r631_i0_fakes import (
    BOOK,
    GOOD_FLOW,
    PACK,
    hashes_of,
    make_repo,
    page_text,
    write_flow,
    write_page,
)

from jarvis.buildbook.book import authored
from jarvis.buildbook.book.authored import AuthoredError, Env
from jarvis.buildbook.gen import compile_pages, snapshot
from jarvis.buildbook.gen.repo import BOOK_DIR, Repo
from jarvis.buildbook.gen.scrub import default_scrubber
from jarvis.buildbook.writer import pages
from jarvis.buildbook.writer.serve import BookPages
from jarvis.buildbook.writer.texts import PagesRefused

C01, MODULE = "pg_card_c01", "pg_module_demo"
DEEP = 3_000  # well past the interpreter's recursion limit, well under the files' caps
# a gzip header, then a deflate block of the reserved type 3: zlib's "invalid block type"
BAD_DEFLATE = bytes.fromhex("1f8b0800000000000003") + b"\xff\xff\xff\xff" + bytes(8)


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    return make_repo(tmp_path)


def _ip(pid: str) -> Any:
    return next(p for p in PACK.pages if p.id == pid)


def _env(root: Path) -> Env:
    return Env(facts=PACK, scrub=default_scrubber(), repo=Repo.from_git(root))


def _stamped(root: Path, pid: str) -> None:
    write_page(root, pid, page_text(pid, hashes_of(root, _ip(pid).refs)))


def _compile(root: Path) -> compile_pages.Compiled:
    return compile_pages.compile_pages(Repo.from_git(root), PACK, scrub=default_scrubber())


# ---- M-1 ----------------------------------------------------------------------------------------
def test_m1_a_page_or_flow_file_that_is_a_link_is_refused_never_followed(root: Path) -> None:
    outside = root.parent / "elsewhere"
    outside.mkdir()
    (outside / "page.md").write_text(page_text(C01, hashes_of(root, _ip(C01).refs)), "utf-8")
    link = root / BOOK / "pages" / f"{C01}.md"
    link.symlink_to(outside / "page.md")
    with pytest.raises(AuthoredError, match="link"):
        authored.load_page(link)
    verdict = authored.judge(root, _ip(C01), _env(root))
    assert verdict.status == "failing" and verdict.page is None
    assert any("link" in p for p in verdict.problems)
    flow = root / BOOK / "flows" / f"{MODULE}.json"
    _stamped(root, MODULE)
    flow.symlink_to(write_flow(outside, "x", GOOD_FLOW))
    with pytest.raises(AuthoredError, match="link"):
        authored.load_flow(flow)
    f = pages.decode_file(_compile(root).pages)
    assert all(p.meta is None for p in f.pages if p.id in (C01, MODULE))


# ---- M-2 ----------------------------------------------------------------------------------------
def test_m2_nesting_past_the_recursion_limit_is_one_plain_error(root: Path) -> None:
    deep = "[" * DEEP + "]" * DEEP
    path = write_page(root, C01, page_text(C01, extra=f"note: {deep}"))
    with pytest.raises(AuthoredError, match="front matter"):
        authored.load_page(path)
    flow = write_flow(root, MODULE, deep)
    with pytest.raises(AuthoredError, match="flows/"):
        authored.load_flow(flow)
    assert authored.judge(root, _ip(C01), _env(root)).status == "failing"


def test_m2_a_page_whose_checks_break_is_the_generator_text(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stamped(root, MODULE)
    write_flow(root, MODULE)
    _stamped(root, C01)
    real = authored.judge

    def judge(top: Path, ip: Any, env: Env) -> Any:
        if ip.id == MODULE:
            raise RuntimeError("a check that breaks")
        return real(top, ip, env)

    monkeypatch.setattr(compile_pages.authored, "judge", judge)
    got = _compile(root)
    f = pages.decode_file(got.pages)
    module, card = pages.page_for(MODULE, f), pages.page_for(C01, f)
    assert module is not None and module.meta is None  # the generator's text
    assert card is not None and card.meta is not None  # the rest of the book is still written
    assert pages.decode_flows(got.flows) == {}
    assert got.counts == {"written": 1, "generator": len(PACK.pages) - 1}


# ---- M-3 ----------------------------------------------------------------------------------------
def test_m3_the_code_snapshot_holds_the_book_folder_the_index_never_does(root: Path) -> None:
    from book_gen_fakes import commit_all

    _stamped(root, C01)
    (root / BOOK / "flow.py").write_text('"""The flowchart model."""\n', encoding="utf-8")
    commit_all(root, "a page and a module")
    repo = Repo.from_git(root)
    assert not [f for f in repo.files if f.startswith(BOOK_DIR)]
    assert {f"{BOOK}/flow.py", f"{BOOK}/pages/{C01}.md", f"{BOOK}/pages/.gitkeep"} <= set(
        repo.book_files
    )
    snap = snapshot.build(repo, snapshot.load_fakes())
    names = set(zipfile.ZipFile(io.BytesIO(snap.data)).namelist())
    top = f"JARVIS-source-{repo.id}/"
    assert {top + f for f in (*repo.files, *repo.book_files)} <= names
    assert top + f"{BOOK}/flow.py" in names
    same = Repo.from_dir(root, sha=repo.sha, committed_at=repo.committed_at)
    assert f"{BOOK}/flow.py" in same.book_files and same.files == repo.files


# ---- L-1 ----------------------------------------------------------------------------------------
def test_l1_a_bad_deflate_block_or_deep_json_is_a_value_error() -> None:
    with pytest.raises(ValueError, match="not gzip"):
        pages.unzipped(BAD_DEFLATE)
    with pytest.raises(ValueError):
        pages.decode_file(BAD_DEFLATE)
    with pytest.raises(ValueError):
        pages.decode_flows(("[" * 100_000 + "]" * 100_000).encode())
    with pytest.raises(ValueError):
        pages.decode_file(gzip.compress(("[" * 100_000 + "]" * 100_000).encode(), mtime=0))


async def test_l1_serving_a_pages_file_with_a_bad_deflate_block_is_unavailable() -> None:
    from book_show_fakes import FixtureSource
    from test_r631_e_serve import _sealed_release, _Vault  # one fake vault for both files

    vault = _Vault(_sealed_release(BAD_DEFLATE, b"{}"), {"pages": BAD_DEFLATE, "flows": b"{}"})
    with pytest.raises(PagesRefused) as no:
        await BookPages(FixtureSource(), vault, uid="uid").index("uid", None)
    assert (no.value.code, no.value.status) == ("unavailable", 503)
