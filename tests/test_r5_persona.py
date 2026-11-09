# tests/test_r5_persona.py -- R5 D9 / D19 (docs/plans/r5-voice.md): the spoken-reply rule now asks
# for the whole answer to be spoken, and the console's voice commands get their own paragraph.
# PERSONA_VERSION p5.0 (bumped once for R5 at I1) covers both.
from __future__ import annotations

import pytest

from jarvis.core import prompts as p


def _flat(rule: str) -> str:
    return " ".join(rule.split())


def test_persona_is_p5_0_bumped_once_for_r5() -> None:
    assert p.PERSONA_VERSION == "p5.0"


def test_voice_rule_keeps_answer_first_and_the_sixty_word_default() -> None:
    r = _flat(p.VOICE_RULE).lower()
    assert "answer first" in r and "60 words" in r
    assert "no markdown" in r and "numbers, dates and times" in r


def test_voice_rule_asks_for_the_whole_answer_when_detail_is_wanted() -> None:
    r = _flat(p.VOICE_RULE).lower()
    assert (
        "when the owner asks for detail, steps, a list or a read-out, give all of it in plain "
        "spoken sentences: it is read aloud in full" in r
    )
    assert "never stop part-way or promise the details elsewhere" in r


def test_the_details_are_on_screen_is_only_for_code_tables_and_links() -> None:
    r = _flat(p.VOICE_RULE).lower()
    assert "on screen" in r
    assert "only for code, tables and links" in r
    assert "give the gist and say the details are on screen" not in r


def test_voice_rule_is_ascii_and_only_on_the_voice_channel() -> None:
    assert p.VOICE_RULE.isascii()
    text = p.build_trailer(tz="Asia/Kolkata", session_id="s", turn_index=1)
    voice = p.build_trailer(tz="Asia/Kolkata", session_id="s", turn_index=1, channel="voice")
    tg = p.build_trailer(tz="Asia/Kolkata", session_id="s", turn_index=1, channel="telegram")
    assert p.VOICE_RULE in voice
    assert p.VOICE_RULE_HEADING not in text and p.VOICE_RULE_HEADING not in tg
    assert "read-out" not in text and "read-out" not in tg


def test_the_control_rule_names_what_the_console_handles_and_where_to_point() -> None:
    r = _flat(p.VOICE_CONTROL_RULE)
    for phrase in ("mic off", "stop", "switch to the keyboard", "switch to <device>"):
        assert phrase in r, phrase
    assert "before a message reaches you" in r and "also with the AI off" in r
    assert "mic button or Ctrl + Shift + Space, or Voice -> Sound devices" in r
    assert "You cannot switch the microphone or sound devices; never claim you did." in r
    assert p.VOICE_CONTROL_RULE.isascii()


@pytest.mark.parametrize("wit", p.WIT_IDS)
def test_the_control_rule_is_in_every_prompt_before_the_tools_rule(wit: str) -> None:
    prompt = p.build_system_prompt(honorific="Sir", wit=wit)
    assert p.VOICE_CONTROL_RULE in prompt
    assert prompt.index(p.PEOPLE_RULE) < prompt.index(p.VOICE_CONTROL_RULE)
    assert prompt.index(p.VOICE_CONTROL_RULE) < prompt.index(p.TOOLS_RULE)


@pytest.mark.parametrize("channel", ["text", "voice", "telegram"])
def test_the_control_rule_is_not_a_per_channel_trailer(channel: str) -> None:
    # it lives in the system prompt, so it applies on every channel and is never repeated
    t = p.build_trailer(tz="Asia/Kolkata", session_id="s", turn_index=1, channel=channel)  # type: ignore[arg-type]
    assert "Voice commands in the console" not in t
