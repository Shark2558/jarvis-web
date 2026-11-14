# tests/test_r14_skill_coverage.py -- R14 D11's check (docs/plans/r14-hardening.md): the fullest
# registry the fakes build (`test_telegram_tool_guard.linked_gateway`, with every R14 part built
# through the real wiring) has every tool filed under exactly one skill, every pattern of the
# catalogue matches a tool, every read tool has a Telegram class, and the register's open reads
# agree with the Telegram guard's own list. `scripts/skill_coverage.py` prints the table.
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from test_telegram_tool_guard import TELEGRAM_SAFE, linked_gateway

from jarvis.skills.ids import SKILL_IDS, SKILL_LABELS
from jarvis.skills.registry import SkillRegister, load_catalogue

ROOT = Path(__file__).resolve().parents[1]
# R14's own open reads: Part C's `skills_open` here, Part A's `vitals_backups` and Part D's
# `maint_service_request` when they are built (the guard's TELEGRAM_SAFE gains them at I1)
R14_OPEN = frozenset({"skills_open", "vitals_backups", "maint_service_request"})


async def test_every_tool_of_the_fullest_registry_is_filed_once() -> None:
    gw = await linked_gateway()
    register = SkillRegister(load_catalogue())
    assert len(gw.registry) >= 135
    assert register.problems(gw.registry) == []
    assert "skills_open" in {s.name for s in gw.registry.specs()}


async def test_every_skill_but_none_is_empty_and_the_core_is_filed() -> None:
    gw = await linked_gateway()
    register = SkillRegister(load_catalogue())
    counts = {s.id: s.tools for s in register.summaries(gw.registry)}
    assert list(counts) == list(SKILL_IDS) and all(n > 0 for n in counts.values()), counts
    assert all(register.skill_of(n) is not None for n in register.catalogue.core)


async def test_the_registers_open_reads_agree_with_the_telegram_guard() -> None:
    gw = await linked_gateway()
    register = SkillRegister(load_catalogue())
    cards = register.cards(gw.registry)
    open_reads = {c.name for c in cards if c.risk == "R1" and c.telegram == "open"}
    assert open_reads - R14_OPEN == set(TELEGRAM_SAFE), sorted(open_reads ^ set(TELEGRAM_SAFE))


async def test_no_skill_holds_so_many_tools_that_one_word_offers_too_many() -> None:
    gw = await linked_gateway()
    register = SkillRegister(load_catalogue())
    names = [s.name for s in gw.registry.specs()]
    for group in register.catalogue.groups:
        held = [n for n in names if register.group_of(n) is group]
        assert len(held) <= 10, (group.id, held)  # a word offers one group, not a whole skill


def test_the_script_prints_the_table_and_passes() -> None:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    run = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "skill_coverage.py")],
        capture_output=True, text=True, env=env, timeout=300, check=False,
    )  # fmt: skip
    assert run.returncode == 0, run.stdout + run.stderr
    for label in SKILL_LABELS.values():
        assert f"| {label} |" in run.stdout, label
    assert "| `skills_open` |" in run.stdout
    assert "problems: none" in run.stdout
