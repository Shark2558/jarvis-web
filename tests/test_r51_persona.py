# tests/test_r51_persona.py -- R5.1 I1, persona p5.1 (docs/plans/r5-1-observations.md D12): JARVIS
# keeps its own Vitals (the owner never types a key's details), "run a systems check" gives the
# full briefing and opens the console's pop-up, and the No-AI switch is the top-bar Brain pill.
from __future__ import annotations

from jarvis.core import prompts as p


def _flat(rule: str) -> str:
    return " ".join(rule.split())


def test_persona_is_p5_1() -> None:
    assert p.PERSONA_VERSION == "p5.1"


def test_vitals_tracks_itself_and_the_owner_never_types_a_key() -> None:
    r = _flat(p.VITALS_RULE)
    assert "JARVIS keeps its own Vitals" in r
    assert "tracked automatically" in r
    assert "The owner never has to type a key's details" in r
    for thing in ("Claude", "Gemini", "Google", "Telegram", "web search", "GitHub", "home laptop"):
        assert thing in r, thing
    assert "Track something JARVIS can't see" in r  # the manual form, for what JARVIS can't see
    assert "tell it a key's limit" not in r  # R4's wording asked the owner to type key details


def test_the_systems_check_gives_the_whole_briefing_with_the_ai_off() -> None:
    r = _flat(p.SYSTEMS_RULE)
    assert '"Run a systems check", "system status"' in r and "systems_check" in r
    assert "its spoken line is the full briefing" in r
    for part in ("every system checked", "what that breaks", "AI spend", "set a reminder"):
        assert part in r, part
    assert "Read that briefing as given" in r
    assert "even with the AI switched off" in r and "makes no model call" in r
    assert "opens the systems-check pop-up" in r


def test_the_no_ai_switch_is_the_top_bar_brain_pill() -> None:
    r = _flat(p.SYSTEMS_RULE)
    assert 'Brain pill in the top bar ("Brain: AI on" / "Brain: No-AI")' in r
    assert "can't flip it from the chat" in r


def test_the_p51_paragraphs_are_ascii_and_in_every_wit_level() -> None:
    for rule in (p.VITALS_RULE, p.SYSTEMS_RULE):
        assert rule.isascii()
        for wit in p.WIT_IDS:
            assert rule in p.build_system_prompt(honorific="Sir", wit=wit)
