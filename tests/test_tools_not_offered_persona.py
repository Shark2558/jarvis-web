# tests/test_tools_not_offered_persona.py - the first real-Claude Phase 0 run after slice 12 (3 Nov)
# got tool-call markup as the reply to "What is on my calendar tomorrow?" when no calendar tool was
# offered. Every wit level now says: a tool that is not offered is not connected, said in words.
from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.core.prompts import PERSONA_VERSION, TOOLS_RULE, WIT_LEVELS, build_system_prompt

CASES = Path(__file__).resolve().parents[1] / "evals" / "phase0" / "cases.jsonl"


def test_persona_version_is_bumped_for_the_rule() -> None:
    assert PERSONA_VERSION == "p5.1"


@pytest.mark.parametrize("wit", [w.id for w in WIT_LEVELS])
def test_every_wit_level_carries_the_not_offered_rule(wit: str) -> None:
    prompt = build_system_prompt(honorific="Sir", wit=wit)
    assert TOOLS_RULE in prompt
    assert "never write tool-call markup" in TOOLS_RULE.lower()
    assert "not connected" in TOOLS_RULE.lower()


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
