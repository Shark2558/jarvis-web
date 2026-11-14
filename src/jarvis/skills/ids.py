# src/jarvis/skills/ids.py
"""The eleven skills (docs/plans/r14-hardening.md D11): the project's ten and Health &
Wellbeing. Ids are stable (data and the register key on them); labels are what he reads. There
is no "Knowledge Base & Memory" skill: those cards are Research & Intel (knowledge and memory)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, get_args

SkillId = Literal[
    "task",
    "research",
    "code",
    "decision",
    "communication",
    "finance",
    "learning",
    "creative",
    "security",
    "automation",
    "health",
]
SKILL_IDS: tuple[SkillId, ...] = get_args(SkillId)
SKILL_LABELS: Mapping[SkillId, str] = {
    "task": "Task & Productivity",
    "research": "Research & Intel",
    "code": "Code & DevOps",
    "decision": "Decision Support",
    "communication": "Communication",
    "finance": "Finance & Analytics",
    "learning": "Learning",
    "creative": "Creative",
    "security": "Security Advisor",
    "automation": "Automation Engine",
    "health": "Health & Wellbeing",
}


@dataclass(frozen=True)
class SkillSummary:
    """One skill as `GET /v1/skills` and "what can you do" show it (no tool text, counts only)."""

    id: SkillId
    label: str
    about: str
    tools: int  # how many registered tools it holds
    without_ai: int  # how many of those work with the AI off


__all__ = ["SKILL_IDS", "SKILL_LABELS", "SkillId", "SkillSummary"]
