# scripts/skill_coverage.py
"""R14 D11: the skill register's table, for the Architecture Guide (card C68) and the build book.

    PYTHONPATH=src python scripts/skill_coverage.py

Builds the fullest registry the test fakes build (`tests/test_telegram_tool_guard.linked_gateway`:
every part on fakes, nothing called, nothing spent), files each tool with
`jarvis.skills.registry.SkillRegister` and prints two Markdown tables: the 11 skills (tools, how
many work with the AI off, what each is about) and every tool (skill, group, risk, permission
rows, Telegram class, No-AI). Tool names and classes only, never a description. Exit 0 when the
register has no problem, 1 (with the problems listed) when it has.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from jarvis.skills.ids import SKILL_LABELS  # noqa: E402
from jarvis.skills.registry import SkillRegister, ToolCard, load_catalogue  # noqa: E402
from jarvis.tools.registry import ToolRegistry  # noqa: E402


async def fullest_registry() -> ToolRegistry:
    from test_telegram_tool_guard import linked_gateway

    return (await linked_gateway()).registry


def _row(card: ToolCard) -> str:
    skill = SKILL_LABELS[card.skill] if card.skill else "(not filed)"
    rows = ", ".join(card.rows) or "risk default"
    telegram = card.telegram or "(no class)"
    no_ai = "yes" if card.without_ai else "no"
    return (
        f"| `{card.name}` | {skill} | {card.group} | {card.risk} | {rows} | {telegram} | {no_ai} |"
    )


def table(register: SkillRegister, registry: ToolRegistry) -> list[str]:
    cards = register.cards(registry)
    out = [
        f"# Skill register (R14 D11): {len(cards)} tools, {len(register.catalogue.skills)} skills",
        "",
        "| Skill | Tools | Without the AI | About |",
        "|---|---|---|---|",
    ]
    out += [
        f"| {s.label} | {s.tools} | {s.without_ai} | {s.about} |"
        for s in register.summaries(registry)
    ]
    out += [
        "",
        "| Tool | Skill | Group | Risk | Rows | Telegram | Without the AI |",
        "|---|---|---|---|---|---|---|",
    ]
    order = {sid: i for i, sid in enumerate(SKILL_LABELS)}
    ranked = sorted(cards, key=lambda c: (order.get(c.skill or "", 99), c.group or "", c.name))
    return out + [_row(c) for c in ranked]


def main() -> int:
    register = SkillRegister(load_catalogue())
    registry = asyncio.run(fullest_registry())
    lines = table(register, registry)
    problems = register.problems(registry)
    lines += ["", "problems: " + ("none" if not problems else str(len(problems)))]
    lines += [f"- {p}" for p in problems]
    sys.stdout.write("\n".join(lines) + "\n")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
