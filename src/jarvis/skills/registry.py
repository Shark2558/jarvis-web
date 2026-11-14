# src/jarvis/skills/registry.py
"""The skill register (docs/plans/r14-hardening.md D11, row 112).

`catalogue.json` (data, beside this file) lists the 11 skills (`skills.ids`), each with a
one-line "about" and its groups: a group's tool patterns (fnmatch; an exact name wins over a
family) and its words for the turn offer (D9). It also names the core tools offered on every
turn, the read tools Telegram answers (`telegram_open`), the tools No-AI mode reaches (`no_ai`)
and the tools another R14 part is still building (`planned`).

`SkillRegister` files a tool by its name and derives its card from the live registry: skill,
group, risk (`Tool.risk`), permission rows (`permissions.groups.groups_for`), Telegram class
(private / personal / home / both from `telegram/rules.py`, or open) and whether it works with
the AI off. `problems(registry)` is the check D11 asks for: a tool with no skill or two, a pattern
that matches nothing, a read tool with no Telegram class, a list naming a tool that isn't there.
Regrouping, words and the offer are data; a new ability still needs a reviewed tool.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any, Final, Literal

from jarvis.core.guardrails import ActionRisk
from jarvis.permissions.groups import groups_for
from jarvis.skills.ids import SKILL_IDS, SKILL_LABELS, SkillId, SkillSummary
from jarvis.telegram import rules as telegram
from jarvis.tools.base import Tool
from jarvis.tools.registry import ToolRegistry

CATALOGUE_VERSION: Final = 1
FILED_KEPT: Final = 1_024  # names whose filing is remembered (the registry's fit many times)
TelegramClass = Literal["private", "personal", "home", "both", "open"]
RISK_WORDS: Mapping[ActionRisk, str] = {
    ActionRisk.READ_ONLY: "R1",
    ActionRisk.REVERSIBLE: "R2",
    ActionRisk.IRREVERSIBLE: "R3",
}
_REFUSED: tuple[tuple[TelegramClass, tuple[str, ...]], ...] = (
    ("private", telegram.PRIVATE_PATTERNS),
    ("personal", telegram.PERSONAL_PATTERNS),
    ("home", telegram.HOME_PATTERNS),
    ("both", telegram.BOTH_PATTERNS),
)
_LISTS = ("core", "planned", "telegram_open", "no_ai")


class CatalogueError(ValueError):
    """The catalogue can't be used (the part is then left out and every tool is offered)."""


@dataclass(frozen=True)
class Group:
    id: str
    skill: SkillId
    words: tuple[str, ...]
    patterns: tuple[str, ...]

    def exact(self, name: str) -> bool:
        return name in self.patterns

    def family(self, name: str) -> bool:
        return any("*" in p and fnmatchcase(name, p) for p in self.patterns)


@dataclass(frozen=True)
class Skill:
    id: SkillId
    label: str
    about: str
    groups: tuple[Group, ...]


@dataclass(frozen=True)
class Catalogue:
    skills: tuple[Skill, ...]
    core: tuple[str, ...]
    telegram_open: frozenset[str]
    no_ai: frozenset[str]
    planned: frozenset[str]

    @property
    def groups(self) -> tuple[Group, ...]:
        return tuple(g for s in self.skills for g in s.groups)


@dataclass(frozen=True)
class ToolCard:
    """One tool as the register files it (names and classes only, never its description)."""

    name: str
    skill: SkillId | None
    group: str | None
    risk: str
    rows: tuple[str, ...]
    telegram: TelegramClass | None
    without_ai: bool


def _names(data: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise CatalogueError(f"'{key}' must be a list of tool names")
    return tuple(value)


def _group(raw: Any, skill: SkillId) -> Group:
    if not isinstance(raw, Mapping) or not isinstance(raw.get("id"), str):
        raise CatalogueError(f"a group of {skill} has no id")
    words, tools = raw.get("words", []), raw.get("tools", [])
    if not isinstance(tools, list) or not tools or not all(isinstance(t, str) and t for t in tools):
        raise CatalogueError(f"group {raw['id']} has no tools")
    if not isinstance(words, list) or not all(isinstance(w, str) and w for w in words):
        raise CatalogueError(f"group {raw['id']}: words must be a list of words")
    if any(w != w.lower() or w.strip() != w for w in words):
        raise CatalogueError(f"group {raw['id']}: words must be lower case, no outer spaces")
    return Group(raw["id"], skill, tuple(words), tuple(tools))


def _skill(raw: Any) -> Skill:
    sid = raw.get("id") if isinstance(raw, Mapping) else None
    if sid not in SKILL_IDS:
        raise CatalogueError(f"unknown skill: {sid!r}")
    about, groups = raw.get("about"), raw.get("groups", [])
    if not isinstance(about, str) or not about or not isinstance(groups, list):
        raise CatalogueError(f"skill {sid} needs an 'about' and a list of groups")
    return Skill(sid, SKILL_LABELS[sid], about, tuple(_group(g, sid) for g in groups))


def parse_catalogue(data: Mapping[str, Any]) -> Catalogue:
    if data.get("version") != CATALOGUE_VERSION:
        raise CatalogueError(f"catalogue version must be {CATALOGUE_VERSION}")
    raw = data.get("skills")
    if not isinstance(raw, list) or len(raw) != len(SKILL_IDS):
        raise CatalogueError("the catalogue must list the eleven skills")
    skills = tuple(_skill(s) for s in raw)
    if tuple(s.id for s in skills) != SKILL_IDS:
        raise CatalogueError("the skills must be listed once each, in skills.ids order")
    ids = [g.id for s in skills for g in s.groups]
    if len(ids) != len(set(ids)):
        raise CatalogueError("a group id is used twice")
    core, planned, open_, no_ai = (_names(data, k) for k in _LISTS)
    return Catalogue(skills, core, frozenset(open_), frozenset(no_ai), frozenset(planned))


def load_catalogue(path: Path | Traversable | None = None) -> Catalogue:
    source = path if path is not None else files("jarvis.skills") / "catalogue.json"
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CatalogueError(f"catalogue unreadable: {type(exc).__name__}") from None
    if not isinstance(data, Mapping):
        raise CatalogueError("catalogue unreadable: not an object")
    return parse_catalogue(data)


def telegram_refusal(name: str) -> TelegramClass | None:
    """The `telegram/rules.py` class that refuses `name` on Telegram by default, if any."""
    for cls, patterns in _REFUSED:
        if any(fnmatchcase(name, p) for p in patterns):
            return cls
    return None


class SkillRegister:
    def __init__(self, catalogue: Catalogue) -> None:
        self.catalogue = catalogue
        self._skills = {s.id: s for s in catalogue.skills}
        self._filed: dict[str, tuple[Group, ...]] = {}

    def filed(self, name: str) -> tuple[Group, ...]:
        """The groups `name` is filed under: those naming it exactly, else its families."""
        got = self._filed.get(name)
        if got is None:
            groups = self.catalogue.groups
            got = tuple(g for g in groups if g.exact(name)) or tuple(
                g for g in groups if g.family(name)
            )
            if len(self._filed) < FILED_KEPT:  # names also come from the model's replayed calls
                self._filed[name] = got
        return got

    def group_of(self, name: str) -> Group | None:
        got = self.filed(name)
        return got[0] if len(got) == 1 else None

    def skill_of(self, name: str) -> SkillId | None:
        group = self.group_of(name)
        return group.skill if group is not None else None

    def skill(self, sid: SkillId) -> Skill:
        return self._skills[sid]

    def telegram_class(self, name: str, risk: ActionRisk) -> TelegramClass | None:
        refused = telegram_refusal(name)
        if refused is not None:
            return refused
        if risk is not ActionRisk.READ_ONLY or name in self.catalogue.telegram_open:
            return "open"  # a write meets Telegram's card rules whatever its class
        return None

    def card(self, tool: Tool) -> ToolCard:
        group = self.group_of(tool.name)
        return ToolCard(
            name=tool.name,
            skill=group.skill if group is not None else None,
            group=group.id if group is not None else None,
            risk=RISK_WORDS[tool.risk],
            rows=tuple(g.id for g in groups_for(tool.name, tool.risk)),
            telegram=self.telegram_class(tool.name, tool.risk),
            without_ai=tool.name in self.catalogue.no_ai,
        )

    def cards(self, registry: ToolRegistry) -> list[ToolCard]:
        return [self.card(t) for t in _tools(registry)]

    def summaries(self, registry: ToolRegistry) -> list[SkillSummary]:
        cards = self.cards(registry)
        return [
            SkillSummary(
                id=s.id,
                label=s.label,
                about=s.about,
                tools=sum(1 for c in cards if c.skill == s.id),
                without_ai=sum(1 for c in cards if c.skill == s.id and c.without_ai),
            )
            for s in self.catalogue.skills
        ]

    def problems(self, registry: ToolRegistry) -> list[str]:
        """The D11 check, one plain line per problem (empty: every tool is filed)."""
        tools = _tools(registry)
        names = {t.name for t in tools}
        out = [p for t in tools for p in self._tool_problems(t)]
        for g in self.catalogue.groups:
            out += [
                f"pattern {p} ({g.skill}/{g.id}) matches nothing"
                for p in g.patterns
                if not any(fnmatchcase(n, p) for n in names)
            ]
        lists = {"core": set(self.catalogue.core), "telegram_open": self.catalogue.telegram_open}
        lists["no_ai"] = self.catalogue.no_ai
        for key, listed in lists.items():
            out += [
                f"'{key}' names {n}, which is not registered"
                for n in sorted(listed)
                if n not in names and n not in self.catalogue.planned
            ]
        return out

    def _tool_problems(self, tool: Tool) -> list[str]:
        filed = self.filed(tool.name)
        out: list[str] = []
        if not filed:
            out.append(f"tool {tool.name} has no skill: file it in skills/catalogue.json")
        elif len(filed) > 1:
            where = ", ".join(f"{g.skill}/{g.id}" for g in filed)
            out.append(f"tool {tool.name} is filed twice: {where}")
        if tool.risk is ActionRisk.READ_ONLY:
            refused = telegram_refusal(tool.name)
            if refused is None and tool.name not in self.catalogue.telegram_open:
                out.append(f"read tool {tool.name} has no Telegram class")
            if refused is not None and tool.name in self.catalogue.telegram_open:
                out.append(f"read tool {tool.name} is both open and {refused} on Telegram")
        return out


def _tools(registry: ToolRegistry) -> list[Tool]:
    return [t for t in (registry.get(s.name) for s in registry.specs()) if t is not None]


__all__ = [
    "CATALOGUE_VERSION",
    "FILED_KEPT",
    "RISK_WORDS",
    "Catalogue",
    "CatalogueError",
    "Group",
    "Skill",
    "SkillRegister",
    "TelegramClass",
    "ToolCard",
    "load_catalogue",
    "parse_catalogue",
    "telegram_refusal",
]
