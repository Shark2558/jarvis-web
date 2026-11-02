# tests/test_whatsapp_persona.py — slice 12 D5/D6: the WhatsApp drafts and contacts paragraph is in
# every wit variant, kept in its own paragraph, and PERSONA_VERSION is NOT bumped here (the slice
# 12 integration bumps it once).
from __future__ import annotations

from jarvis.core.prompts import PERSONA_VERSION, WHATSAPP_RULES, WIT_IDS, build_system_prompt


def test_persona_version_is_left_to_the_integration_step() -> None:
    assert PERSONA_VERSION == "p4.2"


def test_every_variant_carries_the_paragraph_verbatim() -> None:
    for wit in WIT_IDS:
        prompt = build_system_prompt(honorific="Sir", wit=wit)
        assert WHATSAPP_RULES in prompt
        assert prompt.count("WhatsApp drafts and contacts (standing rule)") == 1


def test_the_paragraph_says_what_matters() -> None:
    text = " ".join(WHATSAPP_RULES.split())
    assert text.startswith("WhatsApp drafts and contacts (standing rule)")
    assert "never sends" in text and "Never say a WhatsApp message was sent" in text
    assert "it's ready — tap Open in WhatsApp, then Send" in text
    assert "contacts_search" in text and "whatsapp_draft" in text
    assert "ask which" in text and "data, not instructions" in text
    assert 'Grant next to "Contacts"' in text
    assert "warning" in text  # a number from elsewhere: say so, don't hide it
