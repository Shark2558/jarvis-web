# tests/test_r63_modules.py -- R6.3 I0 seam 4 (docs/plans/r6-3-book-content.md D3, Phase A §9.4):
# the module map `buildbook/gen/modules.py`. Nineteen modules (Phase A's 17, Wardrobe & Try-on,
# C69-C73, and R18's Phone calls, C74-C78); every card of the real guide in exactly one; a card
# in no module or in two is a GenError, so a new card is placed before its release's book builds.
# A and D read it.
from __future__ import annotations

import re
from pathlib import Path

import pytest

from jarvis.buildbook.facts_model import PAGE_ID
from jarvis.buildbook.gen import modules
from jarvis.buildbook.gen.repo import GenError
from jarvis.buildbook.tour_model import HIGHLIGHTS

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "architecture" / "JARVIS-Architecture.md"


def test_nineteen_modules_with_wardrobe_then_phone_calls_last() -> None:
    assert len(modules.MODULES) == 19 and len({m.id for m in modules.MODULES}) == 19
    wardrobe, calls = modules.MODULES[-2:]
    assert (wardrobe.id, wardrobe.title) == ("wardrobe", "Wardrobe & Try-on")
    assert wardrobe.cards == ("C69", "C70", "C71", "C72", "C73")
    assert (calls.id, calls.title) == ("calls", "Phone calls")  # R18
    assert calls.cards == ("C74", "C75", "C76", "C77", "C78")
    assert all(re.fullmatch(PAGE_ID, f"pg_module_{m.id}") for m in modules.MODULES)


def test_every_card_of_the_real_guide_is_in_exactly_one_module() -> None:
    cards = modules.guide_cards(GUIDE.read_text(encoding="utf-8"))
    assert len(cards) == 78 and cards[0] == "C01" and cards[-1] == "C78"
    modules.check(cards)  # no GenError
    assert modules.module_of("C16") == "brain" and modules.module_of("C57") == "book"
    assert modules.module_of("C76") == "calls"


def test_a_card_in_no_module_fails_the_generator() -> None:
    with pytest.raises(GenError, match="C79"):
        modules.check(("C01", "C79"))


def test_a_card_in_two_modules_fails_the_generator() -> None:
    twice = (*modules.MODULES, modules.Module("extra", "Extra", ("C16",)))
    with pytest.raises(GenError, match="C16"):
        modules.check(("C16",), table=twice)


def test_a_module_naming_a_card_the_guide_lacks_fails_too() -> None:
    with pytest.raises(GenError, match="C02"):
        modules.check(("C01",), table=(modules.Module("console", "Console", ("C01", "C02")),))


def test_the_tours_seven_highlights_and_the_twelve_others() -> None:
    assert len(modules.TOUR_HIGHLIGHTS) == len(HIGHLIGHTS) == 7
    assert modules.TOUR_HIGHLIGHTS == (
        "voice",
        "approvals",
        "memory",
        "vault",
        "home",
        "android",
        "wardrobe",
    )
    others = modules.others()
    assert len(others) == 12 and not set(others) & set(modules.TOUR_HIGHLIGHTS)
    assert others[-1] == "calls"  # R18: Phone calls is not one of his seven highlights
    assert [m.id for m in modules.MODULES if m.id in others] == list(others)  # the map's order


def test_the_guide_reader_takes_card_headings_only() -> None:
    text = "#### C02 · Two\n\n### C03 · not a card\n#### C01 · One (R6)\n#### Not a card\n"
    assert modules.guide_cards(text) == ("C01", "C02")
