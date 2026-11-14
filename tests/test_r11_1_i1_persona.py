# tests/test_r11_1_i1_persona.py -- R11.1 I1: one persona version for the release (p11.1) with
# Part A's three sentences (INTEGRATION-A 3.6: the calendar batch, the followed series, the whole
# inbox) beside Part D's PICTURES_RULE, in every wit level, before the tools rule.
from __future__ import annotations

import re

import jarvis.core.prompts as p


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def test_the_release_has_one_persona_version() -> None:
    assert p.PERSONA_VERSION == "p14.0"  # R7's I1 moved it on (tests/test_r7_i1_persona.py)
    src = p.__file__
    with open(src, encoding="utf-8") as fh:
        text = fh.read()
    assert "# p11.1: R11.1" in text  # its change note, like the earlier versions'


def test_part_a_s_three_sentences_are_in_the_plans_rule() -> None:
    rule = _flat(p.PLANS_RULE)
    assert (
        "More than three calendar events in one request: one calendar_create_events call, never "
        "many single calls. When they are sessions of a plan to follow, give series (the plan's "
        "name) and a title_prefix."
    ) in rule
    assert (
        "When the owner says a planned session happened or was skipped, call series_checkin. "
        "Never move sessions yourself: series_reschedule puts the new dates on one approval card."
    ) in rule
    assert "To see all unread mail, by kind: gmail_inbox_summary." in rule
    assert p.PLANS_RULE.isascii() and "PLANS_RULE" in p.__all__
    assert "{" not in p.PLANS_RULE  # no placeholder can be injected (the persona's own rule)


def test_both_r11_1_rules_are_in_every_wit_level_before_the_tools_rule() -> None:
    pictures = p.PICTURES_RULE.replace("{honorific}", "Sir")
    for wit in p.WIT_IDS:
        prompt = p.build_system_prompt(honorific="Sir", wit=wit)
        assert prompt.count(p.PLANS_RULE) == 1, wit
        assert prompt.index(p.HELPERS_RULE) < prompt.index(pictures), wit
        assert prompt.index(pictures) < prompt.index(p.PLANS_RULE) < prompt.index(p.TOOLS_RULE)
