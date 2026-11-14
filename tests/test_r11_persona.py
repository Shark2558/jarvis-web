# tests/test_r11_persona.py -- R11 I1, persona p11.0 (docs/plans/r11-free-helpers.md D22; the parts'
# notes C 4, D 3.5): HELPERS_RULE. JARVIS never pays anyone (a bill is a UPI payment he approves and
# completes with his own PIN); a snoozed or stopped nudge is respected, and "don't remind me to ..."
# about a nudge is nudge_stop, never a reminder (the AI-on path matches the No-AI phrase); alerts
# come from fixed templates; a recipe keeps to his diet and the kitchen's own check decides;
# nutrition values are labelled honestly (US reference values).
from __future__ import annotations

from jarvis.core import prompts as p


def _flat(rule: str) -> str:
    return " ".join(rule.split())


def test_persona_is_p11_0() -> None:
    assert p.PERSONA_VERSION == "p14.0"


def test_the_helpers_rule_says_jarvis_never_pays_and_respects_nudges() -> None:
    r = _flat(p.HELPERS_RULE)
    assert "You never pay anyone." in r
    assert (
        "For a bill you prepare a UPI payment that he approves and completes with his own PIN "
        "in his UPI app" in r
    )
    assert "Respect a snoozed or stopped nudge." in r
    assert "use nudge_stop, never a reminder" in r and "nudge_snooze" in r
    assert "Alerts come from fixed templates" in r


def test_the_helpers_rule_keeps_recipes_to_his_diet_and_labels_nutrition() -> None:
    r = _flat(p.HELPERS_RULE)
    assert "A recipe idea always keeps to his diet" in r
    assert "you never offer a dish it refused" in r
    assert "US reference values (USDA FoodData Central)" in r
    assert "Indian varieties and home recipes can differ" in r


def test_the_helpers_rule_is_ascii_and_in_every_wit_level() -> None:
    assert p.HELPERS_RULE.isascii()
    for wit in p.WIT_IDS:
        prompt = p.build_system_prompt(honorific="Sir", wit=wit)
        assert p.HELPERS_RULE in prompt and prompt.index(p.BOOK_RULE) < prompt.index(p.HELPERS_RULE)
