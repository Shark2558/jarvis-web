# tests/test_r631_i0_exclusion.py -- R6.3.1 I0 (docs/plans/r6-3-1-book-at-build.md D5): the files
# under src/jarvis/buildbook/book/ (the authored pages, flows, their guide and module) are never a
# page's refs, an index entry or a "may cite" entry, and a writer's uncommitted page never trips
# the generator's "tracked files have uncommitted changes" refusal. The checkout these tests run
# in keeps them tracked, yet out of the generator's view.
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from book_gen_fakes import ROOT, commit_all, fixture_repo
from r631_i0_fakes import BOOK, page_text, write_page

from jarvis.buildbook.gen import __main__ as gen_main
from jarvis.buildbook.gen import facts, pages_index
from jarvis.buildbook.gen.modules import Module
from jarvis.buildbook.gen.repo import BOOK_DIR, Repo, documented
from jarvis.buildbook.gen.scrub import default_scrubber
from jarvis.buildbook.writer import packs

S = default_scrubber()
_CARD = """#### {cid} · {title}

| Field | Value |
|---|---|
| Name | {title} |
| What it does | {does} |
| Layer | L4 |
| Skill | Learning |
| Where in the code | {where} |
| Depends on | None |
| Data it keeps | None |
| Outside services | None |
| Cost (₹ a month) | 0 |
| When it fails | It says so plainly. |
| Since | R6.3 |
"""
GUIDE = (
    "Version v6.3.2 · 24 Nov 2026, 09:00 IST · Release R6.3.1 · Status: Current · Owner: Fixture\n"
    "\n# Fixture guide\n\n## 3. Component catalogue\n\n"
    + _CARD.format(cid="C01", title="Demo router", does="Picks a tier.",
                   where="`src/jarvis/demo/router.py`")
    + _CARD.format(cid="C02", title="The book", does="Explains JARVIS.",
                   where="`src/jarvis/buildbook/`")
)  # fmt: skip
FILES = {
    "docs/architecture/JARVIS-Architecture.md": GUIDE,
    "docs/plans/r6-3-1-fixture.md": "# Release R6.3.1 — The fixture\n\n## Risks\n\n- None.\n",
    "src/jarvis/__init__.py": '__version__ = "6.3.2"\n',
    "src/jarvis/demo/__init__.py": '"""The demo."""\n',
    "src/jarvis/demo/router.py": '"""Router."""\n\nMAX_TRIES = 3\n\n\ndef pick() -> str:\n'
    '    return "balanced"\n',
    "src/jarvis/buildbook/__init__.py": '"""The book."""\n\nLIMIT = 7\n\n\ndef read() -> int:\n'
    "    return LIMIT\n",
    f"{BOOK}/__init__.py": '"""Authored pages."""\n',
    f"{BOOK}/authored.py": '"""Authored."""\n\nCAP = 9\n\n\ndef load() -> int:\n    return CAP\n',
    f"{BOOK}/AUTHORING.md": "# How to write a page\n",
    f"{BOOK}/pages/.gitkeep": "",
    f"{BOOK}/flows/.gitkeep": "",
}
TABLE = (Module("demo", "The demo", ("C01", "C02")),)


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    base = tmp_path / "repo"
    for rel, text in FILES.items():
        (base / rel).parent.mkdir(parents=True, exist_ok=True)
        (base / rel).write_text(text, encoding="utf-8")
    write_page(base, "pg_card_c01", page_text("pg_card_c01"))
    commit_all(base)
    return base


def test_the_book_folder_is_named_once() -> None:
    assert BOOK_DIR == BOOK + "/"
    assert not documented(f"{BOOK}/pages/pg_card_c01.md")
    assert documented("src/jarvis/buildbook/x.py")
    assert documented("src/jarvis/buildbook/bookish.py")


def test_a_checkout_never_lists_the_book_folder(root: Path) -> None:
    for repo in (Repo.from_git(root), Repo.from_dir(root, sha="a" * 40, committed_at="x")):
        assert "src/jarvis/buildbook/__init__.py" in repo.files
        assert not [f for f in repo.files if f.startswith(BOOK_DIR)]
        assert repo.under("src/jarvis/buildbook/") == ("src/jarvis/buildbook/__init__.py",)


def test_a_page_being_written_never_makes_the_checkout_dirty(root: Path) -> None:
    write_page(root, "pg_card_c01", page_text("pg_card_c01", {"a.py": "0" * 16}))
    write_page(root, "pg_card_c02", page_text("pg_card_c02"))
    assert Repo.from_git(root).dirty is False
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    assert Repo.from_git(root).dirty is False  # staged pages too
    (root / "src/jarvis/demo/router.py").write_text("MAX_TRIES = 4\n", encoding="utf-8")
    assert Repo.from_git(root).dirty is True


def test_no_ref_index_entry_or_may_cite_entry_is_under_the_book_folder(root: Path) -> None:
    repo = Repo.from_git(root)
    pack = facts.build(repo, S, modules=TABLE)
    pack = pack.model_copy(update={"pages": pages_index.build(repo, pack)})
    book_page = pack.page("pg_card_c02")
    assert book_page is not None and book_page.refs == ("src/jarvis/buildbook/__init__.py",)
    assert "src/jarvis/buildbook/__init__.py:read" in pack.index.symbols
    ix = pack.index
    for name in (
        *ix.paths,
        *ix.symbols,
        *ix.constants,
        *pack.values,
        *(r for p in pack.pages for r in p.refs),
    ):
        assert BOOK not in name, name  # fmt: skip
    for page in pack.pages:
        cited = [repo.text(r) or "" for r in page.refs]
        assert not [a for a in packs.allowed(page, pack, cited) if BOOK in a], page.id


def _error(root: Path, out: Path) -> str:
    assert gen_main.main(["--repo", str(root), "--out", str(out), "--best-effort"]) == 0
    return str(json.loads((out / "release.json").read_text(encoding="utf-8")).get("error") or "")


def test_the_generator_never_refuses_a_page_being_written(tmp_path: Path) -> None:
    root, out = fixture_repo(tmp_path), tmp_path / "out"
    write_page(root, "pg_card_c01", page_text("pg_card_c01"))
    commit_all(root, "a page")
    write_page(root, "pg_card_c01", page_text("pg_card_c01", {"x.py": "1" * 16}))
    write_page(root, "pg_card_c02", page_text("pg_card_c02"))
    assert "uncommitted" not in _error(root, out)  # (the fixture has no licence table)
    (root / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    assert "uncommitted" in _error(root, out)


def test_this_checkout_tracks_the_book_folder_but_never_documents_it() -> None:
    listed = subprocess.run(
        ["git", "ls-files", "--", BOOK], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    assert {f"{BOOK}/pages/.gitkeep", f"{BOOK}/flows/.gitkeep", f"{BOOK}/AUTHORING.md",
            f"{BOOK}/authored.py"} <= set(listed)  # fmt: skip
    assert not [f for f in Repo.from_git(ROOT).files if f.startswith(BOOK_DIR)]
    assert (ROOT / ".gitignore").read_text(encoding="utf-8").count("\n/build/\n") == 1
