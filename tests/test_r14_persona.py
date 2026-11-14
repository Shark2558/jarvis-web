# tests/test_r14_persona.py -- R14 I1, persona p14.0 (docs/plans/r14-hardening.md D14; the
# integration notes INTEGRATION-C "Needs I1" A, INTEGRATION-A #6, INTEGRATION-D #4). With the turn's
# tools narrowed to a few skills (`tool_offer` "by_skill", D9), every passage that spoke of a tool
# "not offered" sends the model to skills_open first; the backups' line and the home-service line
# are said in the Vitals and helpers paragraphs.
from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.core import prompts as p

PROMPTS = Path(p.__file__)


def _flat(rule: str) -> str:
    return " ".join(rule.split())


def test_the_persona_is_p14_0_with_its_note() -> None:
    assert p.PERSONA_VERSION == "p14.0"
    assert "# p14.0: R14" in PROMPTS.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("name", "first"),
    [
        ("_RULES", "call skills_open with the skill that holds it first"),
        ("WEB_RULES", 'call skills_open("research") first'),
        ("DRIVE_RULE", 'call skills_open("research") first'),
        ("TOOLS_RULE", "call skills_open first; never say you can't before that"),
        ("MEDIA_RULES", "call skills_open first (research for Maps, creative for YouTube)"),
    ],
)
def test_each_not_offered_passage_opens_a_skill_before_it_gives_up(name: str, first: str) -> None:
    rule = _flat(getattr(p, name))
    assert first in rule
    assert rule.index("skills_open") < max(
        rule.find("not yet connected"),
        rule.find("not connected"),
        rule.find("not available"),
        rule.find("isn't switched on"),
        rule.find("not set up"),
    )


def test_the_tools_rule_leads_with_d14s_words() -> None:
    rule = _flat(p.TOOLS_RULE)
    assert "This turn you may hold only some of your tools." in rule
    assert "If he asks for something none of them does, call skills_open first" in rule
    assert "Never write tool-call markup" in rule  # the second bullet stays


def test_the_vitals_paragraph_says_the_backups_line() -> None:
    rule = _flat(p.VITALS_RULE)
    assert "Backups are kept 7 days; you tell him when the last one was" in rule
    assert "a restore drill starts only from its card" in rule
    assert "vitals_backups" in rule and "vitals_drill_start" in rule
    # D3: the privacy change is said wherever backups are (the guide, Privacy, the persona)
    assert "leaves the live data at once and the backups within 7 days" in rule


def test_the_helpers_paragraph_says_the_service_request_never_books_or_pays() -> None:
    rule = _flat(p.HELPERS_RULE)
    assert "For a plumber or electrician, call maint_service_request" in rule
    assert "you never book or pay" in rule
    assert "to message a person he picks use whatsapp_draft" in rule


@pytest.mark.parametrize("wit", p.WIT_IDS)
def test_every_wit_level_carries_the_p14_paragraphs_and_the_ascii_ones_stay_ascii(
    wit: str,
) -> None:
    prompt = p.build_system_prompt(honorific="Sir", wit=wit)
    for name in ("_RULES", "WEB_RULES", "DRIVE_RULE", "TOOLS_RULE", "MEDIA_RULES"):
        assert getattr(p, name) in prompt, name
    # ASCII before p14.0, so kept ASCII (the rules, Drive and Maps paragraphs never were)
    for rule in (p.WEB_RULES, p.TOOLS_RULE, p.VITALS_RULE, p.HELPERS_RULE):
        assert rule.isascii() and rule in prompt
