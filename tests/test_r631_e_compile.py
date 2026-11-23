# tests/test_r631_e_compile.py
"""R6.3.1 D4 (docs/plans/r6-3-1-book-at-build.md): the generator compiles the Workshop's authored
pages into the release's pages file (gzipped canonical JSON, every indexed page, filled from the
release's fact pack and checked) and flows file (the FlowSpecs by alias). A missing or failing
page is the generator's plain text, a stale one is still served, and the bytes never change
between two builds of one commit. `write.build` names both files in release.json and writes
them beside book.json."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

import pytest
from book_gen_fakes import FIXTURE_FLOWS, fixture_repo
from r631_i0_fakes import (
    GOOD_BODY,
    PACK,
    ROUTER,
    STORE,
    hashes_of,
    make_repo,
    page_text,
    write_flow,
    write_page,
)

from jarvis.buildbook.gen import compile_pages, fallback, write
from jarvis.buildbook.gen.repo import Repo
from jarvis.buildbook.gen.scrub import default_scrubber
from jarvis.buildbook.writer import pages
from jarvis.buildbook.writer.model import FLOWS_FILE, NOT_WRITTEN, PAGES_FILE

C01, C02, MODULE = "pg_card_c01", "pg_card_c02", "pg_module_demo"


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    return make_repo(tmp_path)


def _stamped(root: Path, pid: str, body: str = GOOD_BODY) -> None:
    refs = next(p for p in PACK.pages if p.id == pid).refs
    write_page(root, pid, page_text(pid, hashes_of(root, refs), body))


def _compile(root: Path) -> compile_pages.Compiled:
    return compile_pages.compile_pages(Repo.from_git(root), PACK, scrub=default_scrubber())


def test_a_written_page_is_filled_with_its_meta_and_flow(root: Path) -> None:
    _stamped(root, MODULE)
    write_flow(root, MODULE)
    got = _compile(root)
    f = pages.decode_file(got.pages)
    page = pages.page_for(MODULE, f)
    assert page is not None and page.meta is not None
    assert page.meta.model_dump(mode="json") == {
        "written_by": "Workshop · Mark XXIV",
        "written_on": "2026-11-24",
        "release": PACK.release.id if PACK.release else "",
        "version": "v6.3.2",
    }
    how = next(s.text for s in page.sections if s.id == "how")
    assert "at most 3 times" in how and "{{fact:" not in how
    assert next(s for s in page.sections if s.id == "code").refs == (ROUTER, STORE)
    flows = pages.decode_flows(got.flows)
    assert set(flows) == {MODULE} and flows[MODULE]["edges"][0]["from"] == "ask"
    assert "from_" not in json.dumps(flows) and "ref" in flows[MODULE]["nodes"][1]
    assert got.counts == {"written": 1, "generator": len(PACK.pages) - 1}


def test_missing_and_failing_pages_are_the_generator_text(root: Path) -> None:
    _stamped(root, C02, GOOD_BODY.replace("Nothing: it runs", "It costs 42 rupees; it runs"))
    f = pages.decode_file(_compile(root).pages)
    for pid in (C02, "pg_screen_phone"):
        page = pages.page_for(pid, f)
        assert page is not None and page.meta is None
        assert page.sections[0].text.startswith(f"{NOT_WRITTEN}. This page is about ")
    _stamped(root, MODULE, GOOD_BODY.replace("Nothing: it runs", "It costs 42 rupees; it runs"))
    write_flow(root, MODULE)
    assert pages.decode_flows(_compile(root).flows) == {}  # a failing page's chart goes too


def test_a_stale_page_is_still_served(root: Path) -> None:
    write_page(root, C01, page_text(C01))  # never stamped: stale, not failing
    page = pages.page_for(C01, pages.decode_file(_compile(root).pages))
    assert page is not None and page.meta is not None


def test_a_module_without_its_flowchart_fails_and_is_the_generator_text(root: Path) -> None:
    _stamped(root, MODULE)
    page = pages.page_for(MODULE, pages.decode_file(_compile(root).pages))
    assert page is not None and page.meta is None
    write_flow(root, MODULE)
    page = pages.page_for(MODULE, pages.decode_file(_compile(root).pages))
    assert page is not None and page.meta is not None


def test_every_indexed_page_in_order_with_its_module_titles_and_limitations(root: Path) -> None:
    f = pages.decode_file(_compile(root).pages)
    assert [p.id for p in f.pages] == [p.id for p in PACK.pages]
    assert f.release == (PACK.release.id if PACK.release else "")
    assert f.limitations == len(PACK.limitations)
    assert {c.id for part in pages.view(f).parts for c in part.chapters} >= {"demo"}


def test_the_bytes_are_canonical_and_the_same_twice(root: Path) -> None:
    _stamped(root, MODULE)
    write_flow(root, MODULE)
    one, two = _compile(root), _compile(root)
    assert (one.pages, one.flows) == (two.pages, two.flows)
    assert one.pages[4:8] == b"\x00\x00\x00\x00"  # gzip mtime 0
    raw = gzip.decompress(one.pages)
    assert raw == json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False).encode()  # fmt: skip


def test_the_generator_writes_and_names_both_files(tmp_path: Path) -> None:
    repo = Repo.from_git(fixture_repo(tmp_path))
    built = write.build(repo, write.Options(flows=FIXTURE_FLOWS, licence=lambda _n: "MIT"))
    rel = built.release
    assert rel.pages_sha256 == hashlib.sha256(built.pages).hexdigest()
    assert rel.flows_sha256 == hashlib.sha256(built.flows).hexdigest()
    assert rel.kinds() == ("book", "source", "pages", "flows")
    out = tmp_path / "_book"
    write.write(out, built)
    assert (out / PAGES_FILE).read_bytes() == built.pages
    assert (out / FLOWS_FILE).read_bytes() == built.flows
    assert "pages_sha256" in json.loads((out / write.RELEASE_FILE).read_text())
    fallback.clear(out)
    assert not (out / PAGES_FILE).exists() and not (out / FLOWS_FILE).exists()
