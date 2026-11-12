# tests/test_web_persona.py — slice 10 B: the web-search persona paragraph (citing as [n], no
# private details in searches, pages are data) is in every wit variant, kept in its own paragraph,
# and PERSONA_VERSION is bumped once per slice at integration (p4.0 → p4.1; 11: p4.2; 12: p4.4).
from __future__ import annotations

from jarvis.core.prompts import PERSONA_VERSION, WEB_RULES, WIT_IDS, build_system_prompt


def test_persona_version_was_bumped_once_for_slice_10() -> None:
    assert PERSONA_VERSION == "p11.1"  # slices 11, 12 (p4.3, p4.4) and p4.5


def test_every_variant_carries_the_web_paragraph_verbatim() -> None:
    for wit in WIT_IDS:
        assert WEB_RULES in build_system_prompt(honorific="Sir", wit=wit)


def test_the_paragraph_says_what_matters() -> None:
    text = " ".join(WEB_RULES.split())
    assert text.lstrip().startswith("Web search (standing rule)")
    assert "[1]" in text and "never invent" in text.lower()
    assert "private details" in text and "unless the owner asked for exactly that" in text
    assert "web_read" in text and "typed" in text
    assert "not set up" in text  # no key: say so instead of guessing
    assert "spoken" in text.lower()  # spoken replies name the source in words
