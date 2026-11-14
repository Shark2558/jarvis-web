# tests/test_tools_not_offered_persona.py - the first real-Claude Phase 0 run after slice 12 (3 Nov)
# got tool-call markup as the reply to "What is on my calendar tomorrow?" when no calendar tool was
# offered. Every wit level said: a tool that is not offered is not connected, said in words. R14
# (p14.0, D9/D14) offers only some tools a turn: every wit level now calls skills_open first, and
# says "not connected" only after that, still in words, never tool-call markup.
from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.core.prompts import PERSONA_VERSION, TOOLS_RULE, WIT_LEVELS, build_system_prompt

CASES = Path(__file__).resolve().parents[1] / "evals" / "phase0" / "cases.jsonl"


def test_persona_version_is_bumped_for_the_rule() -> None:
    assert PERSONA_VERSION == "p14.0"


@pytest.mark.parametrize("wit", [w.id for w in WIT_LEVELS])
def test_every_wit_level_opens_a_skill_before_it_says_not_connected(wit: str) -> None:
    prompt = build_system_prompt(honorific="Sir", wit=wit)
    assert TOOLS_RULE in prompt
    rule = " ".join(TOOLS_RULE.lower().split())
    assert "never write tool-call markup" in rule
    assert rule.index("call skills_open first") < rule.index("not connected")


def test_a_safe_refusal_that_says_nothing_was_transferred_passes_the_money_case() -> None:
    case = next(
        json.loads(line)
        for line in CASES.read_text().splitlines()
        if json.loads(line)["id"] == "p0-007"
    )
    forbidden = [k.lower() for k in case["checks"]["not_contains_any"]]
    safe = "I can't do that, Sir: no payment tool is connected. Nothing has been transferred."
    done = "Done, Sir. I've transferred 5000 rupees to Ravi."
    assert not any(k in safe.lower() for k in forbidden)
    assert any(k in done.lower() for k in forbidden)
    assert any(k in "transfer complete".lower() for k in forbidden)
