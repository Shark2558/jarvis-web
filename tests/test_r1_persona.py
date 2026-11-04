# tests/test_r1_persona.py -- R1 I1: persona p4.6 (the Telegram trailer). Part 2 adds the groceries,
# packages and family paragraphs here.
from __future__ import annotations

from typing import Any

import pytest

from jarvis.core import prompts as p

KW: dict[str, Any] = {"tz": "Asia/Kolkata", "session_id": "s", "turn_index": 1}


def test_persona_is_p4_6() -> None:
    assert p.PERSONA_VERSION == "p4.6"


def test_the_telegram_rule_says_what_telegram_can_and_cannot_do() -> None:
    r = p.TELEGRAM_RULE
    assert "plain text" in r.lower() and "markdown" in r.lower()
    assert "120 words" in r
    assert "console" in r
    assert "approv" in r.lower()  # nothing irreversible is approved here
    assert "off by default" in r.lower() and "email" in r.lower()
    assert "never paste" in r.lower()


def test_the_telegram_rule_is_short_and_ascii() -> None:
    assert len(p.TELEGRAM_RULE.split()) <= 120
    assert p.TELEGRAM_RULE.isascii()


@pytest.mark.parametrize("channel", ["text", "voice"])
def test_only_a_telegram_turn_gets_the_telegram_rule(channel: str) -> None:
    assert p.TELEGRAM_RULE not in p.build_trailer(channel=channel, **KW)  # type: ignore[arg-type]
    assert p.TELEGRAM_RULE in p.build_trailer(channel="telegram", **KW)
