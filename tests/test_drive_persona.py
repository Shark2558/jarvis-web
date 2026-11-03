# tests/test_drive_persona.py — slice 12 D1/D10: the Drive standing rule is its own paragraph in
# every wit level's persona (PERSONA_VERSION is bumped once at integration, not here).
from __future__ import annotations

import pytest

from jarvis.core.prompts import DRIVE_RULE, WIT_IDS, build_system_prompt


@pytest.mark.parametrize("wit", WIT_IDS)
def test_every_persona_carries_the_drive_rule(wit: str) -> None:
    assert DRIVE_RULE in build_system_prompt(honorific="Sir", wit=wit)


def test_the_rule_says_chosen_folders_read_only_and_untrusted() -> None:
    text = " ".join(DRIVE_RULE.split())
    assert "drive_folders" in text and "drive_search" in text and "drive_read" in text
    assert "chosen" in text and "Integrations" in text
    assert "read-only" in text or "can't change" in text
    assert "never instructions" in text
    assert "Not in your chosen folders" in text or "not in your chosen folders" in text


def test_the_rule_says_what_to_say_when_drive_is_off_here() -> None:
    """Final review: JARVIS_DRIVE is off when the deploy could not switch the Drive API on (or
    the row is Never): no drive_* tool is offered, and the model says so plainly."""
    text = " ".join(DRIVE_RULE.split())
    assert "If no drive_* tool is offered" in text and "isn't switched on" in text
