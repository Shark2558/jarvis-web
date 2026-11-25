# tests/test_r64_i0_chapters.py
"""R6.4 D5 (docs/plans/r6-4-book-look.md): the full book's 26 narrated chapters, deterministic from
the pages index: 8 story chapters (each its `pg_chapter_*` page) and 18 module chapters (the
`pg_module_*` page, its parts' cards in the module map's order, then the screens and outside
services `HOMES` gives it). No page is in two chapters; a page in none stays readable."""

from __future__ import annotations

from typing import Any

import pytest
from r631_i0_fakes import PACK

from jarvis.buildbook.book import chapters as ch
from jarvis.buildbook.facts_model import CHAPTERS, FactPack
from jarvis.buildbook.gen.modules import MODULES


def test_story_then_module_chapters_from_the_index_in_its_order() -> None:
    got = ch.chapters(PACK.pages, homes={"pg_screen_phone": "demo"})
    assert [(c.id, c.kind, c.title) for c in got] == [
        ("story_example", "story", "The running example"),
        ("module_demo", "module", "The demo"),
    ]
    assert got[0].pages == ("pg_chapter_example",)
    assert got[1].pages == ("pg_module_demo", "pg_card_c01", "pg_card_c02", "pg_screen_phone")


def test_a_page_in_no_chapter_stays_out_and_a_home_without_its_module_is_ignored() -> None:
    got = ch.chapters(PACK.pages, homes={"pg_service_anthropic": "nowhere"})
    assert all("pg_service_anthropic" not in c.pages for c in got)
    assert "pg_screen_phone" not in ch.pages_in(got)


def test_the_chapter_id_and_its_lead_page() -> None:
    assert ch.chapter_id("pg_chapter_what") == "story_what"
    assert ch.chapter_id("pg_module_vault") == "module_vault"
    assert ch.chapter_id("pg_card_c07") is None
    assert ch.find(ch.chapters(PACK.pages), "module_demo") is not None
    assert ch.find(ch.chapters(PACK.pages), "module_nope") is None


def test_the_homes_table_names_only_screens_and_services_of_known_modules() -> None:
    modules = {m.id for m in MODULES}
    for page_id, module in ch.HOMES.items():
        assert page_id.startswith(("pg_screen_", "pg_service_")), page_id
        assert module in modules, (page_id, module)


# ---- the real tree ----------------------------------------------------------------------------
@pytest.fixture(scope="module")
def real() -> FactPack:
    from jarvis.buildbook.gen import facts_cache
    from jarvis.buildbook.gen.repo import Repo

    pack, _ = facts_cache.facts_for(Repo.from_git(None), facts_cache.build_pack, note=lambda: None)
    return pack


def test_the_real_book_has_26_chapters_covering_every_page_once(real: FactPack) -> None:
    got = ch.chapters(real.pages)
    assert len(got) == 26
    assert [c.id for c in got[:8]] == [f"story_{cid}" for cid, _ in CHAPTERS]
    assert [c.id for c in got[8:]] == [f"module_{m.id}" for m in MODULES]
    every = [p for c in got for p in c.pages]
    assert len(every) == len(set(every)), "a page is in two chapters"
    indexed = {p.id for p in real.pages}
    assert set(every) <= indexed, "a chapter names a page the index doesn't have"
    assert set(every) == indexed, f"pages in no chapter: {sorted(indexed - set(every))}"
    assert set(ch.HOMES) <= indexed, "HOMES names a page the index doesn't have"


def test_the_vault_chapter_is_its_five_pages_in_order(real: FactPack) -> None:
    vault: Any = ch.find(ch.chapters(real.pages), "module_vault")
    assert vault is not None and vault.title == "Vault and documents"
    assert vault.pages == (
        "pg_module_vault", "pg_card_c07", "pg_card_c42", "pg_card_c43", "pg_screen_vault",
    )  # fmt: skip


def test_every_module_chapter_starts_with_its_module_then_its_cards(real: FactPack) -> None:
    for c, m in zip(ch.chapters(real.pages)[8:], MODULES, strict=True):
        cards = tuple(f"pg_card_{n.lower()}" for n in m.cards)
        assert c.pages[: 1 + len(cards)] == (f"pg_module_{m.id}", *cards), m.id
        assert all(p.startswith(("pg_screen_", "pg_service_")) for p in c.pages[1 + len(cards) :])
