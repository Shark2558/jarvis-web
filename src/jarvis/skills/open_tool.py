# src/jarvis/skills/open_tool.py
"""`skills_open(skill)` (docs/plans/r14-hardening.md D9, D14's TOOLS_RULE): the model holds only
some of its tools in a turn; when none of them does what he asks, it opens one of the 11 skills
and holds that skill's tools from its next step (`skills.offer` sees the call in the round).

R1, no side effect, no permission row (the risk default applies), open on Telegram; it runs
through `jarvis.tools.gateway` like every tool. Its answer is the register's own fixed data (the
skill's label, what it is about, its tools' names), never other people's words, so reading it
taints nothing (`trusted_output`). An unknown skill is refused by its argument check.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final

from jarvis.core.guardrails import ActionRisk
from jarvis.skills.ids import SKILL_IDS
from jarvis.skills.offer import OPEN_TOOL
from jarvis.skills.registry import SkillRegister
from jarvis.tools.base import Tool
from jarvis.tools.registry import ToolRegistry

OPEN_WORDS: Final = "Opened a skill"
NEXT_STEP: Final = "Its tools are yours from your next step; nothing was done."
_LEAD = (
    "Open one of your skills when none of the tools you hold this turn can do what he asks: "
    "from your next step you also hold that skill's tools. It does nothing else. Skills: "
)


def _description(register: SkillRegister) -> str:
    return _LEAD + "; ".join(f"{s.id} ({s.label})" for s in register.catalogue.skills) + "."


def _check(args: dict[str, Any]) -> None:
    if args.get("skill") not in SKILL_IDS:
        raise ValueError("unknown skill: choose one of " + ", ".join(SKILL_IDS))


def skills_open_tool(register: SkillRegister, registry: Callable[[], ToolRegistry | None]) -> Tool:
    """The tool; `registry` is read late (the gateway is built after the part)."""

    async def run(args: dict[str, Any]) -> dict[str, Any]:
        skill = register.skill(args["skill"])
        live = registry()
        held = [s.name for s in live.specs()] if live is not None else []
        names = [n for n in held if register.skill_of(n) == skill.id and n != OPEN_TOOL]
        return {
            "skill": skill.id,
            "label": skill.label,
            "about": skill.about,
            "tools": names,
            "note": NEXT_STEP,
        }

    schema = {
        "type": "object",
        "properties": {"skill": {"type": "string", "enum": list(SKILL_IDS)}},
        "required": ["skill"],
        "additionalProperties": False,
    }
    return Tool(
        OPEN_TOOL,
        _description(register),
        schema,
        ActionRisk.READ_ONLY,
        run,
        agent="skills",
        summary_template="Open the {skill} skill",
        check=_check,
        trusted_output=True,
        activity_words=OPEN_WORDS,
    )


__all__ = ["NEXT_STEP", "OPEN_WORDS", "skills_open_tool"]
