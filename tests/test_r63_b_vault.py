# tests/test_r63_b_vault.py -- R6.3 D11, D12 (plan review H3): a release's pages file (R6.3.1 D4:
# v2, the whole full book, compiled at build time) round trips gzipped under its cap, a written
# page has its six sections and code refs, and a page is changed when a file it cites or its card
# changes, or it is new (`carry.tree_of`, kept as the hashing). R6.3.1 D8: the AI pages' own
# vault, the free carry and the sweep went with the runtime writer (their tests with them).
from __future__ import annotations

from typing import Any

import pytest
from r63_fake_brains import GOOD_DRAFT
from r63_fakes import FIXTURE_FACTS, source_zip
from r63_fakes_b import files

from jarvis.buildbook.writer import carry, checks, pages
from jarvis.buildbook.writer.model import PAGES_FILE_CAP_BYTES, PageMeta, PagesFile

RID = "6363636"
KNOWN = tuple(p.id for p in FIXTURE_FACTS.pages)
META = PageMeta(written_by="Workshop · Mark XXIV", written_on="2026-11-24", release=RID)


# ---- the pages file (D11) ------------------------------------------------------------------------
def _written(page_id: str, text: str = GOOD_DRAFT) -> Any:
    ip = FIXTURE_FACTS.page(page_id)
    assert ip is not None
    parsed = checks.parse(text)
    assert parsed is not None
    return pages.written(ip, parsed, META)


def test_a_pages_file_round_trips_gzipped_under_its_cap() -> None:
    f = PagesFile(release=RID, pages=(_written("pg_card_c01"),), modules={"demo": "Demo"})
    data = pages.encode_file(f)
    assert data[:2] == b"\x1f\x8b" and len(data) <= PAGES_FILE_CAP_BYTES
    assert pages.decode_file(data) == f and pages.encode_file(f) == data
    with pytest.raises(ValueError):
        pages.decode_file(b"not gzip")


def test_a_written_page_has_the_six_sections_and_its_code_refs() -> None:
    page = _written("pg_card_c01")
    assert [s.id for s in page.sections] == ["plain", "example", "how", "costs", "fails", "code"]
    assert page.sections[1].heading == "Example (made up)"
    assert page.sections[-1].refs == ("src/jarvis/demo/router.py",) and page.meta == META


# ---- the changed pages, by content (D11, D12, H3) ----------------------------------------
def test_a_page_is_changed_when_a_file_it_cites_or_its_card_changes_or_it_is_new() -> None:
    old = carry.tree_of(source_zip())
    same = carry.tree_of(source_zip())
    store = carry.tree_of(source_zip(files({"src/jarvis/demo/store.py": '"""Changed."""\n'})))
    assert carry.changed_ids(FIXTURE_FACTS, KNOWN, old, same) == ()
    moved = carry.changed_ids(FIXTURE_FACTS, KNOWN, old, store)
    assert "pg_card_c02" in moved and "pg_card_c01" not in moved and "pg_module_demo" in moved
    guide = files()["docs/architecture/JARVIS-Architecture.md"].replace("Keeps the demo's", "Keeps")
    card = carry.tree_of(source_zip(files({"docs/architecture/JARVIS-Architecture.md": guide})))
    assert "pg_card_c02" in carry.changed_ids(FIXTURE_FACTS, KNOWN, old, card)
    assert carry.changed_ids(FIXTURE_FACTS, KNOWN[:-1], old, same) == ("pg_service_anthropic",)
