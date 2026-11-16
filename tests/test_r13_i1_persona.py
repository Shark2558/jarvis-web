# tests/test_r13_i1_persona.py -- R13 I1, persona p13.0 (docs/plans/r13-wardrobe.md D21): the
# wardrobe's standing rule (`WARDROBE_RULE`): clothes, shoes and worn accessories live in the
# wardrobe (Things when it has none), a change starts from the piece's id, a private piece is "a
# private basic" outside the Wardrobe tab, an outfit comes from rules with their reasons, laundry
# is prepared and never ordered, paid or called, and archive, restore, merge and remove are cards.
# Nothing compares versions: the number follows the release (R13 = v13.0.0 -> p13.0).
from __future__ import annotations

from pathlib import Path

from jarvis.core import prompts as p

PROMPTS = Path(p.__file__)


def _flat(rule: str) -> str:
    return " ".join(rule.split())


def test_the_persona_is_p13_0_with_its_note() -> None:
    assert p.PERSONA_VERSION == "p13.0"
    assert "# p13.0: R13" in PROMPTS.read_text(encoding="utf-8")


def test_the_wardrobe_rule_says_d21s_words() -> None:
    rule = _flat(p.WARDROBE_RULE)
    for words in (
        "Clothing, footwear and worn accessories are in the wardrobe",
        "find and move them with the wardrobe tools; try Things when the wardrobe has none",
        "Before a change, find the piece and use its id",
        "Never name a private piece outside the Wardrobe tab; say 'a private basic'",
        "An outfit comes from wardrobe rules with their reasons",
        "say a piece is ready only when the tool says so",
        "Laundry is prepared, never ordered, paid or called",
        "Archive, restore, merge and remove are cards",
    ):
        assert words in rule, words


def test_the_rule_is_in_the_prompt_once_before_the_tools_rule() -> None:
    prompt = p.build_system_prompt(honorific="Sir")
    assert prompt.count(p.WARDROBE_RULE) == 1
    assert prompt.index(p.WARDROBE_RULE) < prompt.index(p.TOOLS_RULE)
    assert "WARDROBE_RULE" in p.__all__


def test_the_rule_is_plain_ascii() -> None:
    assert p.WARDROBE_RULE.isascii()
