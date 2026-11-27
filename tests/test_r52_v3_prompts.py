# tests/test_r52_v3_prompts.py -- R5.2 V3: the voice session's ~120 prompts in 4 blocks (plan
# 3.3): 30 "Hey Jarvis" said 30 ways, 80 held-out lines (the ~20 Google minutes), his own words
# in blocks 2 and 4 under ids that never carry them, every command's key phrase.
from __future__ import annotations

from collections import Counter

from jarvis.localspeech.protocol import PROMPT_ID, PromptKind
from jarvis.voice.commands import COMMAND_HINTS
from jarvis.voice.profile import BLOCKS, PROMPTS_TARGET, WAKE_PROMPTS
from jarvis.voice.session_prompts import (
    BLOCK_TITLES,
    COMMANDS,
    LINES,
    WAKE_WAYS,
    WAKES,
    build_prompts,
    scored,
)


def test_120_prompts_in_4_blocks_of_30_with_30_ways_of_hey_jarvis() -> None:
    plan = build_prompts()
    assert len(plan.prompts) == PROMPTS_TARGET == sum(LINES.values()) + sum(WAKES.values())
    assert Counter(p.block for p in plan.prompts) == {b: 30 for b in range(1, BLOCKS + 1)}
    wake = [p for p in plan.prompts if p.kind is PromptKind.WAKE]
    assert len(wake) == WAKE_PROMPTS == len(WAKE_WAYS) == len({p.how for p in wake})
    assert all(p.text == "Hey Jarvis" for p in wake)
    assert set(BLOCK_TITLES) == {1, 2, 3, 4}


def test_held_out_lines_are_80_spread_and_six_wake_words() -> None:
    plan = build_prompts()
    held = [p for p in plan.prompts if scored(p)]
    assert len(held) == 80  # 80 x Google's 15 s step = the comparison's 20 minutes
    assert Counter(p.block for p in held) == {1: 20, 2: 20, 3: 20, 4: 20}
    assert sum(p.held_out for p in plan.prompts if p.kind is PromptKind.WAKE) == 6
    for block in range(1, 5):
        lines = [p for p in plan.prompts if p.block == block and p.kind is not PromptKind.WAKE]
        assert lines[-1].held_out or lines[-2].held_out  # training lines are spread, not last


def test_ids_are_unique_valid_and_never_carry_his_words() -> None:
    import re

    words = ["Zephyrine", "Quillon Bay"]
    plan = build_prompts(words)
    ids = [p.id for p in plan.prompts]
    assert len(ids) == len(set(ids)) and all(re.fullmatch(PROMPT_ID, i) for i in ids)
    assert not any("zeph" in i or "quill" in i for i in ids)
    mine = [p for p in plan.prompts if p.id in plan.own]
    assert {p.block for p in mine} == {2, 4} and len(mine) == 4
    assert all(p.kind is PromptKind.WORDS for p in mine)
    assert plan.keys[mine[0].id] == "Zephyrine"


def test_his_words_fill_block_2_first_then_generic_places_and_names() -> None:
    plan = build_prompts([f"Word{chr(97 + i)}" for i in range(14)] + ["worda"])  # one repeated
    block2 = [p for p in plan.prompts if p.block == 2 and p.kind is not PromptKind.WAKE]
    assert sum(p.kind is PromptKind.WORDS for p in block2) == 10 == len(block2) - 12
    block4 = [p for p in plan.prompts if p.block == 4 and p.kind is PromptKind.WORDS]
    assert len(block4) == 5
    assert len(build_prompts().prompts) == len(plan.prompts)


def test_commands_are_the_consoles_own_and_carry_their_key() -> None:
    hints = {h.casefold() for h in COMMAND_HINTS}
    assert all(key in hints for _, key in COMMANDS)
    plan = build_prompts()
    commands = [p for p in plan.prompts if p.kind is PromptKind.COMMAND]
    assert all(p.id in plan.keys for p in commands)
    numbers = [p for p in plan.prompts if p.kind is PromptKind.NUMBERS]
    assert len(numbers) == 23 and not any(p.id in plan.keys for p in numbers)
    assert plan.by_id(commands[0].id) == commands[0] and plan.by_id("nope") is None
