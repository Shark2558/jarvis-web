# tests/test_r3_persona.py -- R3 I1: persona p4.8, now p5.0 (bumped at R4 and R5 I1; "Persona"):
# the home, camera, faces and alerts paragraphs, each pinned on its own; the Telegram trailer names
# the third switch and says disarming is only in the console.
from __future__ import annotations

import pytest

from jarvis.core import prompts as p


def _flat(rule: str) -> str:
    return " ".join(rule.split())


def test_persona_is_p5_0() -> None:
    assert p.PERSONA_VERSION == "p5.0"


@pytest.mark.parametrize("name", ["HOME_RULES", "CAMERA_RULES", "FACES_RULE", "ALERTS_RULE"])
def test_each_r3_paragraph_is_in_every_prompt_and_ascii(name: str) -> None:
    rule = getattr(p, name)
    assert rule.isascii()
    for wit in p.WIT_IDS:
        assert rule in p.build_system_prompt(honorific="Sir", wit=wit)


def test_the_r3_paragraphs_come_before_the_tools_rule() -> None:
    prompt = p.build_system_prompt(honorific="Sir")
    assert prompt.index(p.PRIVACY_RULE) < prompt.index(p.HOME_RULES) < prompt.index(p.TOOLS_RULE)


def test_home_says_armed_only_when_confirmed_and_never_disarms() -> None:
    r = _flat(p.HOME_RULES)
    assert "home_status" in r and "home_devices" in r
    assert '"your home laptop is off or asleep"' in r and "never guess" in r
    assert "armed only when home_arm returns confirmed: true" in r
    assert "no_zones" in r and "protects nothing" in r
    assert "You cannot turn the alarm off" in r
    assert "call home_disarm, which only tells the owner to press Disarm in the Home panel" in r
    assert "also when asked from Telegram" in r
    assert "Never say the alarm is off" in r


def test_home_rules_match_the_permission_rows_and_name_no_pronoun() -> None:
    """Integrated review M11: arming by voice has no card (permission row home_arm); disarming,
    locks, gates and heaters wait for the owner's sign-in in the console (home_secure); the rule
    no longer says alarms "always ask for the passkey" or "his"."""
    r = _flat(p.HOME_RULES)
    assert "Arming needs no card." in r
    assert (
        "Disarming, locks, gates and heaters always wait for the owner's sign-in in the console."
        in r
    )
    assert "his passkey" not in r and " his " not in f" {r} "
    assert "alarms and heaters always ask" not in r and "Locks, gates, alarms" not in r
    assert p.PERSONA_VERSION == "p5.0"  # R3 is unreleased: the wording changes in place


def test_camera_never_names_or_describes_an_unknown_person() -> None:
    r = _flat(p.CAMERA_RULES)
    assert "camera_history" in r and "times, places and counts" in r
    assert "never sees pictures" in r and "never describes how anyone looks" in r
    assert '"someone JARVIS didn\'t recognise"' in r
    assert 'never a name, never a guess, never "probably"' in r
    assert "exactly as the tool gives them" in r and "Frigate on his laptop" in r


def test_faces_need_consent_and_are_never_changed_from_the_chat() -> None:
    r = _flat(p.FACES_RULE)
    assert "Faces panel with their consent" in r and "guardian's for a child" in r
    assert "can't be added or removed from the chat" in r
    assert "Faces or Privacy" in r and "faces_list" in r


def test_alerts_settings_live_in_the_panel() -> None:
    r = _flat(p.ALERTS_RULE)
    assert "Integrations -> Alerts" in r and "can't change them from the chat" in r
    assert "Burglar and hazard alerts always ring" in r


def test_the_telegram_trailer_names_the_third_switch_and_the_console_disarm() -> None:
    t = _flat(p.TELEGRAM_RULE)
    assert "third switch, also off by default" in t
    assert "Disarming the alarm is only ever in the console's Home panel" in t
    assert t.isascii()
