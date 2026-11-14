# tests/test_r14_c_register.py -- R14 Part C, D11 (docs/plans/r14-hardening.md): the skill
# register. The catalogue (data) files every tool under one group of one of the 11 skills by its
# name (an exact name wins over a family); each tool's card carries its skill, risk, permission
# rows, Telegram class and whether it works with the AI off; `problems` is the coverage check.
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from jarvis.core.guardrails import ActionRisk
from jarvis.skills.ids import SKILL_IDS, SKILL_LABELS
from jarvis.skills.registry import (
    FILED_KEPT,
    CatalogueError,
    SkillRegister,
    load_catalogue,
    parse_catalogue,
)
from jarvis.tools.base import Tool
from jarvis.tools.registry import ToolRegistry

R1, R2, R3 = ActionRisk.READ_ONLY, ActionRisk.REVERSIBLE, ActionRisk.IRREVERSIBLE


def _tool(name: str, risk: ActionRisk = R1) -> Tool:
    async def run(_: dict[str, Any]) -> str:
        return "ok"

    return Tool(name, f"the {name} tool", {"type": "object", "properties": {}}, risk, run)


def _registry(*tools: Tool) -> ToolRegistry:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return reg


def _data(**over: Any) -> dict[str, Any]:
    """A small valid catalogue: every skill, two of them with groups."""
    skills: list[dict[str, Any]] = [
        {"id": sid, "about": f"about {sid}", "groups": []} for sid in SKILL_IDS
    ]
    skills[0]["groups"] = [
        {"id": "calendar", "tools": ["calendar_*"], "words": ["calendar", "meeting"]},
        {"id": "kitchen_block", "tools": ["calendar_kitchen_blocks"], "words": ["cook"]},
    ]
    skills[1]["groups"] = [{"id": "web", "tools": ["web_*"], "words": ["search"]}]
    data: dict[str, Any] = {
        "version": 1,
        "core": ["calendar_list_events"],
        "planned": [],
        "telegram_open": ["calendar_list_events", "web_search"],
        "no_ai": ["calendar_list_events"],
        "skills": skills,
    }
    data.update(over)
    return data


def test_the_shipped_catalogue_names_the_eleven_skills_in_order() -> None:
    cat = load_catalogue()
    assert tuple(s.id for s in cat.skills) == SKILL_IDS
    assert all(s.label == SKILL_LABELS[s.id] and s.about for s in cat.skills)
    assert cat.core == ("skills_open", "reminder_add", "calendar_list_events", "memory_search")
    ids = [g.id for g in cat.groups]
    assert len(ids) == len(set(ids))  # group ids are unique across skills
    assert all(g.words and g.patterns for g in cat.groups)
    assert all(w == w.lower() and w.strip() == w for g in cat.groups for w in g.words)


def test_an_exact_name_wins_over_a_family() -> None:
    reg = SkillRegister(parse_catalogue(_data()))
    assert reg.group_of("calendar_kitchen_blocks").id == "kitchen_block"  # type: ignore[union-attr]
    assert reg.group_of("calendar_list_events").id == "calendar"  # type: ignore[union-attr]
    assert reg.skill_of("web_read") == "research"
    assert reg.group_of("vault_list") is None and reg.skill_of("vault_list") is None


def test_two_families_for_one_tool_is_filed_twice() -> None:
    data = _data()
    data["skills"][2]["groups"] = [{"id": "dup", "tools": ["web_*"], "words": ["x"]}]
    reg = SkillRegister(parse_catalogue(data))
    assert reg.group_of("web_read") is None  # ambiguous: nobody may guess
    problems = reg.problems(_registry(_tool("web_read"), _tool("calendar_list_events")))
    assert any("web_read" in p and "filed twice" in p for p in problems)


def test_the_check_names_every_kind_of_problem() -> None:
    reg = SkillRegister(parse_catalogue(_data()))
    tools = _registry(
        _tool("calendar_list_events"),
        _tool("web_search"),
        _tool("web_read"),  # a read with no Telegram class
        _tool("vault_list", R2),  # filed nowhere
    )
    problems = reg.problems(tools)
    assert any("vault_list" in p and "no skill" in p for p in problems)
    assert any("web_read" in p and "Telegram" in p for p in problems)
    assert any("calendar_kitchen_blocks" in p and "matches nothing" in p for p in problems)
    assert not any("web_search" in p for p in problems)


def test_a_stale_list_name_is_a_problem_unless_planned() -> None:
    data = _data(telegram_open=["calendar_list_events", "gone_tool"], no_ai=["later_tool"])
    reg = SkillRegister(parse_catalogue(data))
    tools = _registry(_tool("calendar_list_events"), _tool("calendar_kitchen_blocks", R2))
    tools.register(_tool("web_search"))
    problems = reg.problems(tools)
    assert any("gone_tool" in p for p in problems) and any("later_tool" in p for p in problems)
    planned = SkillRegister(parse_catalogue({**data, "planned": ["gone_tool", "later_tool"]}))
    assert not any("_tool" in p for p in planned.problems(tools))


def test_a_read_open_on_telegram_and_refused_there_too_is_a_problem() -> None:
    data = _data(telegram_open=["calendar_list_events", "web_search", "gmail_search"])
    data["skills"][4]["groups"] = [{"id": "email", "tools": ["gmail_*"], "words": ["mail"]}]
    reg = SkillRegister(parse_catalogue(data))
    tools = _registry(
        _tool("calendar_list_events"),
        _tool("calendar_kitchen_blocks", R2),
        _tool("web_search"),
        _tool("gmail_search"),
    )
    assert any("gmail_search" in p and "both" in p for p in reg.problems(tools))


def test_cards_carry_skill_risk_rows_telegram_and_no_ai() -> None:
    reg = SkillRegister(load_catalogue())
    cards = {c.name: c for c in reg.cards(_registry(
        _tool("gmail_search"), _tool("gmail_send", R3), _tool("calendar_list_events"),
        _tool("vault_list"), _tool("home_devices"), _tool("deleted_restore", R2),
        _tool("skills_open"),
    ))}  # fmt: skip
    assert cards["gmail_search"].telegram == "private" and cards["gmail_search"].skill == (
        "communication"
    )
    assert cards["gmail_send"].risk == "R3" and "email_send" in cards["gmail_send"].rows
    assert cards["calendar_list_events"].telegram == "open"
    assert cards["calendar_list_events"].without_ai and not cards["gmail_search"].without_ai
    assert cards["vault_list"].telegram == "personal" and cards["vault_list"].skill == "security"
    assert cards["home_devices"].telegram == "home" and cards["home_devices"].skill == "automation"
    assert cards["deleted_restore"].telegram == "both"
    assert cards["skills_open"].rows == () and cards["skills_open"].skill == "code"


def test_summaries_count_each_skills_tools_and_those_without_the_ai() -> None:
    reg = SkillRegister(load_catalogue())
    tools = _registry(
        _tool("calendar_list_events"), _tool("reminder_add", R2), _tool("gmail_search"),
        _tool("not_filed_anywhere"),
    )  # fmt: skip
    got = {s.id: s for s in reg.summaries(tools)}
    assert list(got) == list(SKILL_IDS)
    assert (got["task"].tools, got["task"].without_ai) == (2, 2)
    assert (got["communication"].tools, got["communication"].without_ai) == (1, 0)
    assert got["finance"].tools == 0 and got["task"].label == "Task & Productivity"


@pytest.mark.parametrize(
    ("change", "why"),
    [
        (lambda d: d["skills"].pop(), "eleven"),
        (lambda d: d["skills"][0].update(id="knowledge"), "unknown skill"),
        (lambda d: d["skills"].reverse(), "order"),
        (lambda d: d["skills"][1]["groups"].append(dict(d["skills"][0]["groups"][0])), "twice"),
        (lambda d: d["skills"][0]["groups"][0].update(words=["Calendar"]), "lower"),
        (lambda d: d["skills"][0]["groups"][0].update(tools=[]), "no tools"),
        (lambda d: d["skills"][0]["groups"][0].update(tools=[""]), "no tools"),  # review L2
        (lambda d: d.update(core="calendar_list_events"), "list"),
        (lambda d: d.update(version=2), "version"),
    ],
)
def test_a_broken_catalogue_is_refused(change: Any, why: str) -> None:
    data = _data()
    change(data)
    with pytest.raises(CatalogueError, match=why):
        parse_catalogue(data)


def test_a_catalogue_file_that_cannot_be_read_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "catalogue.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(CatalogueError, match="unreadable"):
        load_catalogue(bad)
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_data()), encoding="utf-8")
    assert load_catalogue(good).core == ("calendar_list_events",)


def test_the_filing_memory_is_bounded() -> None:
    """Python review L2: names also come from replayed model calls; a made-up name is still
    filed right, but only the first FILED_KEPT names are remembered."""
    reg = SkillRegister(load_catalogue())
    for n in range(FILED_KEPT + 300):
        assert reg.skill_of(f"gmail_made_up_{n}") == "communication"
    assert len(reg._filed) <= FILED_KEPT
