# tests/test_r63_a_pages.py -- R6.3 part A, D3 (docs/plans/r6-3-book-content.md) and row 380's
# "grows" half: the full book's pages index. Every page in a fixed order (the eight chapters, the
# modules, the cards under their modules, the screens and the show, the services), each with its
# refs full and scrubbed (a folder expanded to its files) and its sources; a new card gets its own
# page at the next release, and a card in no module stops the generator.
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest
from r63_fakes_a import DEMO, a_repo, repo_of

from jarvis.buildbook.facts_model import CHAPTERS, PAGE_ID, FactPack, load_facts
from jarvis.buildbook.gen import facts, flows, pages_index, write
from jarvis.buildbook.gen.modules import Module
from jarvis.buildbook.gen.repo import GenError, Repo
from jarvis.buildbook.gen.scrub import Scrubber, default_scrubber

S = default_scrubber()
WITH_C74 = (Module("demo", "The demo", ("C01", "C02", "C03", "C74")),)


def _pages(repo: Repo, table: tuple[Module, ...] = DEMO) -> FactPack:
    pack = facts.build(repo, S, modules=table)
    return pack.model_copy(update={"pages": pages_index.build(repo, pack)})


def test_pages_in_their_fixed_order(tmp_path: Path) -> None:
    pack = _pages(a_repo(tmp_path))
    ids = [p.id for p in pack.pages]
    chapters = [f"pg_chapter_{c}" for c, _ in CHAPTERS]
    assert ids[:8] == chapters
    assert ids[8:] == [
        "pg_module_demo",
        "pg_card_c01",
        "pg_card_c02",
        "pg_card_c03",
        "pg_screen_chat",
        "pg_screen_demo",
        "pg_screen_show",
        "pg_service_anthropic",
        "pg_service_firestore",
    ]
    assert len(set(ids)) == len(ids)
    assert all(re.match(PAGE_ID, i) for i in ids)


def test_each_page_s_part_chapter_refs_and_sources(tmp_path: Path) -> None:
    pack = _pages(a_repo(tmp_path))
    card = pack.page("pg_card_c01")
    assert card is not None
    assert (card.kind, card.part, card.chapter, card.title) == (
        "card",
        "parts",
        "demo",
        "Demo router",
    )
    assert card.refs == ("src/jarvis/demo/router.py",) and card.sources == ("C01",)
    module = pack.page("pg_module_demo")
    assert module is not None and module.part == "modules" and module.chapter == ""
    assert module.sources == ("C01", "C02", "C03")
    assert set(module.refs) == {
        "src/jarvis/demo/router.py",
        "src/jarvis/demo/store.py",
        "src/jarvis/api/static/console-demo.js",
    }
    service = pack.page("pg_service_firestore")
    assert service is not None and service.sources == ("C02",)
    assert service.refs == ("src/jarvis/demo/store.py",)
    screen = pack.page("pg_screen_demo")
    assert screen is not None and "src/jarvis/demo/routes.py" in screen.refs
    assert screen.sources == ("C03",)  # the card citing one of its files
    example = pack.page("pg_chapter_example")
    assert (
        example is not None and example.part == "plain" and example.title == "The running example"
    )


def test_a_folder_reference_is_expanded_to_its_files(tmp_path: Path) -> None:
    pack = _pages(a_repo(tmp_path, c74=True), WITH_C74)
    page = pack.page("pg_card_c74")
    assert page is not None
    assert "src/jarvis/demo/routes.py" in page.refs and "src/jarvis/demo/router.py" in page.refs
    assert not any(r.endswith("/") for p in pack.pages for r in p.refs)
    assert all(r in pack.index.paths for p in pack.pages for r in p.refs)


def test_row380_a_new_card_gets_its_own_page_at_the_next_release(tmp_path: Path) -> None:
    """The pages-index half of row 380 (grows): a C74 card placed in a module gets
    `pg_card_c74` in that module's chapter with its refs; a C74 in no module stops the generator."""
    before = _pages(a_repo(tmp_path / "before"))
    assert before.page("pg_card_c74") is None
    after = _pages(a_repo(tmp_path / "after", c74=True), WITH_C74)
    page = after.page("pg_card_c74")
    assert page is not None and page.chapter == "demo" and page.sources == ("C74",)
    assert page.title == "Demo extra" and page.refs
    assert [p.id for p in after.pages].index("pg_card_c74") == [p.id for p in after.pages].index(
        "pg_card_c03"
    ) + 1
    telegram = after.page("pg_service_telegram")  # a service only C74 names gets its page too
    assert telegram is not None and telegram.sources == ("C74",)
    with pytest.raises(GenError, match="C74"):
        _pages(a_repo(tmp_path / "loose", c74=True), DEMO)


FLOWS = tuple((fid, fid, (("The demo router", "demo.router:pick"),)) for fid in flows.FLOW_IDS)
OPTS = write.Options(flows=FLOWS, layer_of={"demo": "L4", "config": "X"}, licence=lambda _n: "MIT")


def test_the_generator_refuses_a_card_in_no_module(tmp_path: Path) -> None:
    """Through the join with the real module map: C74 is placed nowhere, so no book is built."""
    with pytest.raises(GenError, match="cards in no module.*C74"):
        write.build(a_repo(tmp_path, c74=True), OPTS)


def test_the_join_writes_the_pages_into_facts_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = facts.build
    monkeypatch.setattr(facts, "build", lambda r, s: original(r, s, modules=DEMO))
    pack = load_facts(write.build(a_repo(tmp_path), OPTS).facts)
    assert [p.id for p in pack.pages][:8] == [f"pg_chapter_{c}" for c, _ in CHAPTERS]
    assert pack.page("pg_card_c02") is not None and pack.release is not None


def test_a_card_s_scrubbed_folder_still_expands(tmp_path: Path) -> None:
    handle = "zorblaxton"
    scrub = Scrubber(frozenset({hashlib.sha256(handle.encode()).hexdigest()}))
    guide = (
        "# Guide\n\n#### C01 · Phone\n\n| Field | Value |\n|---|---|\n"
        f"| Where in the code | `android/app/src/main/java/io/{handle}/` |\n"
        "| Outside services | None |\n\n## 11. Roadmap (PLANNED)\n"
    )
    files = {
        "docs/architecture/JARVIS-Architecture.md": guide,
        f"android/app/src/main/java/io/{handle}/Main.kt": "package x\n",
        f"android/app/src/main/java/io/{handle}/Sos.kt": "package x\n",
    }
    repo = repo_of(tmp_path, files)
    table = (Module("android", "The Android app", ("C01",)),)
    pack = facts.build(repo, scrub, modules=table)
    pages = pages_index.build(repo, pack)
    card = next(p for p in pages if p.id == "pg_card_c01")
    assert card.refs == (
        "android/app/src/main/java/io/[removed]/Main.kt",
        "android/app/src/main/java/io/[removed]/Sos.kt",
    )
    assert handle not in pack.model_dump_json() and handle not in str(pages)
