# tests/test_media_persona.py — slice 12 D3/D4: the Maps and YouTube standing rule, its own
# paragraph (merges stay simple; the integration step bumps PERSONA_VERSION once for the slice).
from __future__ import annotations

from jarvis.core.prompts import MEDIA_RULES, PERSONA_VERSION, WIT_IDS, build_system_prompt


def test_every_wit_level_carries_the_media_rule() -> None:
    for wit in WIT_IDS:
        assert MEDIA_RULES in build_system_prompt(honorific="Sir", wit=wit)


def test_the_rule_says_what_matters() -> None:
    text = " ".join(MEDIA_RULES.split()).lower()
    assert "maps_route" in text and "'home'" in text and "'work'" in text
    assert "never say a video is playing" in text and "play" in text
    assert "grant" in text and "integrations" in text
    assert "other people's words" in text
    assert "not set up" in text


def test_persona_version_was_bumped_at_the_slice_12_integration() -> None:
    assert PERSONA_VERSION == "p4.8"  # 12: p4.3, p4.4; p4.5 tools rule
