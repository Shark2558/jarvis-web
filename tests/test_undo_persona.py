# tests/test_undo_persona.py — slice 11: the persona tells the model that the owner's own deletes
# run at once and can be undone (and how), which deletes still wait for approval, and the cap.
# Its own paragraph (UNDO_RULES) so the slice 11 merges stay simple; PERSONA_VERSION is bumped
# once for the whole slice at integration, not here.
from __future__ import annotations

from jarvis.core.prompts import PERSONA_VERSION, UNDO_RULES, WIT_IDS, build_system_prompt


def test_every_wit_variant_carries_the_undo_paragraph() -> None:
    for wit in WIT_IDS:
        assert UNDO_RULES in build_system_prompt(honorific="Sir", wit=wit)


def test_the_undo_paragraph_says_how_to_undo_and_what_still_waits() -> None:
    text = " ".join(UNDO_RULES.split())
    for words in (
        "Recently deleted",
        "30 days",
        "deleted_restore",
        "deleted_list",
        "undo_id",
        '"undo"',
        "without guests",
        "other people",
        "repeating",
        "Docs or Chat",
        "10",
    ):
        assert words in text, words


def test_old_rules_no_longer_say_every_delete_waits() -> None:
    prompt = " ".join(build_system_prompt(honorific="Sir").split())
    assert "deleting always waits for the owner's approval" not in prompt
    assert "deleting what can't be undone" in prompt


def test_persona_version_was_bumped_once_per_slice() -> None:
    assert PERSONA_VERSION == "p4.4"  # slice 11: p4.2 (reminders, undo, look-up); 12: p4.4
