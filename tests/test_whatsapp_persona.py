# tests/test_whatsapp_persona.py — slice 12 D5/D6: the WhatsApp drafts and contacts paragraph is in
# every wit variant, kept in its own paragraph; the slice 12 integration bumped PERSONA_VERSION
# once (p4.3) for Drive, Maps + YouTube and this paragraph together, and the final review once more
# (p4.4) for the Drive rule's "not switched on" line.
from __future__ import annotations

from jarvis.core.prompts import (
    DRIVE_RULE,
    MEDIA_RULES,
    PERSONA_VERSION,
    WHATSAPP_RULES,
    WIT_IDS,
    build_system_prompt,
)


def test_persona_version_was_bumped_for_slice_12() -> None:
    assert PERSONA_VERSION == "p5.1"


def test_the_slice_12_paragraphs_are_each_there_once_in_order() -> None:
    for wit in WIT_IDS:
        prompt = build_system_prompt(honorific="Sir", wit=wit)
        for rule in (DRIVE_RULE, MEDIA_RULES, WHATSAPP_RULES):
            assert prompt.count(rule) == 1
        at = [prompt.index(rule) for rule in (DRIVE_RULE, MEDIA_RULES, WHATSAPP_RULES)]
        assert at == sorted(at)  # Drive, then Maps and YouTube, then contacts and WhatsApp


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
