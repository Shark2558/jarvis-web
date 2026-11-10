# tests/test_r6_persona.py -- R6 I1, persona p6.0 (docs/plans/r6-build-book.md D17): BOOK_RULE.
# The build book opens only in the console's Book panel (the passkey AND a fresh Google sign-in);
# in a chat JARVIS doesn't have it, points there and never recites the book or the code. The
# guest's talk-through prompt is a separate one (buildbook/prompt.py, bg1), never the persona's
# "...speaking to is the owner".
from __future__ import annotations

from jarvis.buildbook import prompt as guest
from jarvis.core import prompts as p


def _flat(rule: str) -> str:
    return " ".join(rule.split())


def test_persona_is_p6_0() -> None:
    assert p.PERSONA_VERSION == "p6.0"


def test_the_book_rule_points_to_the_panel_and_never_recites() -> None:
    r = _flat(p.BOOK_RULE)
    assert (
        "The build book opens only in the console's Book panel with the owner's passkey and a "
        "fresh Google sign-in." in r
    )
    assert "In a chat you don't have it: point there; never recite the book or the code." in r


def test_the_book_rule_is_ascii_and_in_every_wit_level() -> None:
    assert p.BOOK_RULE.isascii()
    for wit in p.WIT_IDS:
        assert p.BOOK_RULE in p.build_system_prompt(honorific="Sir", wit=wit)


def test_the_guest_prompt_is_its_own() -> None:
    assert guest.GUEST_PROMPT_VERSION == "bg1"
    assert "speaking to is the owner" not in guest.GUEST_SYSTEM
    assert p.BOOK_RULE not in guest.GUEST_SYSTEM and "{honorific}" not in guest.GUEST_SYSTEM
