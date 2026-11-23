# tests/test_r631_i1_checks.py
"""R6.3.1 I1: the page checks the writers hit — a plain "₹0" is not a typed number, and a bare
file name in the index (`Dockerfile`, `Makefile`) is a citable reference."""

from __future__ import annotations

from jarvis.buildbook.facts_model import FactIndex, FactPack, IndexedPage
from jarvis.buildbook.gen.scrub import default_scrubber
from jarvis.buildbook.writer import checks

PAGE = IndexedPage(
    id="pg_chapter_technology",
    kind="chapter",
    title="Technology",
    part="plain",
    refs=("Dockerfile", "Makefile", "src/jarvis/config.py"),
)
PACK = FactPack(index=FactIndex(paths=("Dockerfile", "Makefile", "src/jarvis/config.py")))


def _ctx() -> checks.Context:
    return checks.Context(page=PAGE, facts=PACK, scrub=default_scrubber(), emails=())


def test_rupee_zero_is_not_a_typed_number() -> None:
    assert checks._numbers_ok("It costs ₹0 a month.", PACK)
    assert checks._numbers_ok("₹0, always.", PACK)


def test_other_rupee_amounts_are_still_typed_numbers() -> None:
    assert not checks._numbers_ok("It costs ₹05 a month.", PACK)
    assert not checks._numbers_ok("It costs ₹0.5 a reply.", PACK)
    assert not checks._numbers_ok("It costs ₹10 a month.", PACK)


def test_bare_file_names_in_the_index_are_citable() -> None:
    ctx = _ctx()
    assert checks._ref_ok("Dockerfile", ctx)
    assert checks._ref_ok("Makefile", ctx)


def test_an_unknown_bare_name_is_still_refused() -> None:
    assert not checks._ref_ok("Procfile", _ctx())
